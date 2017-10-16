"""
Discussion forum signal handlers
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.dispatch import receiver

from django_comment_common.signals import (
    thread_created,
    comment_created,
    thread_deleted,
    comment_deleted,
    thread_voted,
    comment_voted,
    thread_followed,
    thread_unfollowed,
)
import lms.lib.comment_client as cc
from social_engagement.tasks import task_update_user_engagement_score


@receiver(thread_deleted)
@receiver(comment_deleted)
@receiver(thread_voted)
@receiver(comment_voted)
def thread_comment_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score
    """
    post = kwargs['post']
    course_id = getattr(post, 'course_id', None)
    user_id = getattr(post, 'user_id', None)
    social_engagement_enabled = settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT', False)

    if social_engagement_enabled:
        if course_id and user_id:
            task_update_user_engagement_score.delay(unicode(course_id), user_id)

        # present only in two cases: thread_deleted & comment_deleted
        if 'involved_users' in kwargs:
            involved_users = kwargs['involved_users']
            users = User.objects.filter(username__in=involved_users).exclude(id=user_id)

            for user in users:
                task_update_user_engagement_score.delay(unicode(course_id), user.id)


@receiver(thread_created)
def thread_created_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    action_user = kwargs['user']
    social_engagement_enabled = settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT', False)

    if social_engagement_enabled and course_id and action_user:
        task_update_user_engagement_score.delay(unicode(course_id), action_user.id)


@receiver(comment_created)
def comment_created_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score
    """
    comment = kwargs['post']
    course_id = getattr(comment, 'course_id', None)
    thread_id = getattr(comment, 'thread_id', None)
    parent_id = getattr(comment, 'parent_id', None)
    action_user = kwargs['user']
    social_engagement_enabled = settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT', False)

    if social_engagement_enabled and course_id and action_user:
        task_update_user_engagement_score.delay(unicode(course_id), action_user.id)

        # a response is a reply to a thread
        # a comment is a reply to a response
        is_comment = not thread_id and parent_id

        if is_comment:
            # If creating a comment, then we don't have the original thread_id
            # so we have to get it from the parent
            comment = cc.Comment.find(parent_id)
            thread_id = comment.thread_id
            replying_to_id = comment.user_id

            # update the engagement of the author of the response
            task_update_user_engagement_score.delay(unicode(course_id), replying_to_id)

        if thread_id:
            thread = cc.Thread.find(thread_id)

            # IMPORTANT: we have to use getattr here as
            # otherwise the property will not get fetched
            # from cs_comment_service
            thread_user_id = int(getattr(thread, 'user_id', 0))

            # update the engagement score of the thread creator
            # as well
            task_update_user_engagement_score.delay(unicode(course_id), thread_user_id)


@receiver(thread_followed)
@receiver(thread_unfollowed)
def thread_follow_unfollow_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    user_id = getattr(thread, 'user_id', None)
    action_user = kwargs['user']  # user who followed or un-followed thread
    social_engagement_enabled = settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT', False)

    if social_engagement_enabled and course_id and user_id and action_user.id != user_id:
        task_update_user_engagement_score.delay(unicode(course_id), user_id)
