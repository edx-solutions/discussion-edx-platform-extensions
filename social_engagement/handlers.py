"""
Discussion forum signal handlers
"""
import logging

from django.conf import settings
from django.dispatch import receiver

import openedx.core.djangoapps.django_comment_common.comment_client as cc
from openedx.core.djangoapps.django_comment_common.signals import (comment_created, comment_deleted,
                                           thread_created, thread_deleted,
                                           thread_followed,
                                           thread_or_comment_flagged,
                                           thread_unfollowed, thread_voted)
from social_engagement.tasks import task_update_user_engagement

log = logging.getLogger(__name__)


@receiver(thread_deleted)
@receiver(thread_voted)
def thread_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for deleted and voted thread (or voted comment).
    TODO: And also, for some reason, on voted comment.
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    user_id = getattr(thread, 'user_id', None)

    # present if thread_deleted
    if 'involved_users' in kwargs:
        users = kwargs['involved_users']
        for user, user_data in users.items():
            _decrement(user, course_id, user_data)

    # thread or comment voted
    else:
        change = _decrement if kwargs.get('undo') else _increment
        change(user_id, course_id, 'num_upvotes')


@receiver(thread_created)
def thread_created_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for created thread.
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    action_user = kwargs['user']

    if action_user:
        _increment(action_user.id, course_id, 'num_threads')


@receiver(comment_deleted)
def comment_deleted_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for deleted comment.
    """
    post = kwargs['post']
    course_id = getattr(post, 'course_id', None)

    if 'involved_users' in kwargs:
        users = kwargs['involved_users']
        for user, user_data in users.items():
            _decrement(user, course_id, user_data)


@receiver(comment_created)
def comment_created_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for created comment.
    """
    comment = kwargs['post']
    course_id = getattr(comment, 'course_id', None)
    thread_id = getattr(comment, 'thread_id', None)
    parent_id = getattr(comment, 'parent_id', None)
    action_user = kwargs['user']

    if action_user:
        # a comment is a reply to a thread
        # a response is a reply to a comment or a response

        # It's a comment
        if not parent_id:
            _increment(action_user.id, course_id, 'num_comments')

        # It's a reply
        else:
            _increment(action_user.id, course_id, 'num_replies')

        if thread_id:
            thread = cc.Thread.find(thread_id)

            # IMPORTANT: we have to use getattr here as
            # otherwise the property will not get fetched
            # from cs_comment_service
            try:
                thread_user_id = int(getattr(thread, 'user_id'))

                # update the engagement score of the thread creator as well
                _increment(thread_user_id, course_id, 'num_comments_generated')
            except AttributeError as error:
                log.exception(error)


@receiver(thread_followed)
def thread_followed_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for followed thread.
    """
    _thread_followed_or_unfollowed_handler(followed=True, **kwargs)


@receiver(thread_unfollowed)
def thread_unfollowed_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for un-followed thread.
    """
    _thread_followed_or_unfollowed_handler(**kwargs)


def _thread_followed_or_unfollowed_handler(**kwargs):
    """
    Updates user social engagement score for followed or un-followed thread.
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    user_id = getattr(thread, 'user_id', None)
    action_user = kwargs['user']  # user who followed or un-followed thread

    try:
        if user_id and str(action_user.id) != user_id:
            if kwargs.get('followed'):
                _increment(user_id, course_id, 'num_thread_followers')
            else:
                _decrement(user_id, course_id, 'num_thread_followers')
    except AttributeError as error:
        log.exception(error)


@receiver(thread_or_comment_flagged)
def thread_or_comment_flagged_handler(sender, **kwargs):  # pylint: disable=unused-argument
    thread_or_comment = kwargs['post']
    course_id = getattr(thread_or_comment, 'course_id', None)
    user_id = getattr(thread_or_comment, 'user_id', None)

    change = _decrement if kwargs.get('undo') else _increment
    change(user_id, course_id, 'num_flagged')


def _increment(*args, **kwargs):
    """
    A facade for handling incrementation.
    """
    _handle_change_after_signal(*args, **kwargs)


def _decrement(*args, **kwargs):
    """
    A facade for handling decrementation.
    """
    _handle_change_after_signal(*args, increment=False, **kwargs)


def _handle_change_after_signal(user_id, course_id, param, increment=True, items=1):
    """
    Validate settings and input and run Celery task for saving changed parameters.

    :param param: `str` with stat that should be changed or
                  `dict[str, int]` (`stat: number_of_occurrences`) with the stats that should be changed
    """
    if settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT') and user_id and course_id:
        task_update_user_engagement.delay(user_id, course_id, param, increment, items)
