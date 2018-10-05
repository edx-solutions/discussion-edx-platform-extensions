"""
Discussion forum signal handlers
"""
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
from social_engagement.tasks import task_handle_change_after_signal


@receiver(thread_deleted)
@receiver(thread_voted)
def thread_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for deleted and voted thread.
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

    # thread voted
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


@receiver(comment_deleted)  # TODO - WTF - the thread_voted signal is also sent here o.O
@receiver(comment_voted)
def comment_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score for deleted (and voted) comment.
    """
    post = kwargs['post']
    course_id = getattr(post, 'course_id', None)

    # present if comment_deleted
    if 'involved_users' in kwargs:
        users = kwargs['involved_users']
        for user, user_data in users.items():
            _decrement(user, course_id, user_data)

    # comment voted
    # TODO: investigate - it looks like the thread_voted signal is also sent with comment_voted
    # else:
    #     _increment(user_id, course_id, 'num_upvotes')


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
        _increment(action_user.id, course_id, 'num_replies')

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
            _increment(replying_to_id, course_id, 'num_comments')

        if thread_id:
            thread = cc.Thread.find(thread_id)

            # IMPORTANT: we have to use getattr here as
            # otherwise the property will not get fetched
            # from cs_comment_service
            thread_user_id = int(getattr(thread, 'user_id', 0))

            # update the engagement score of the thread creator
            # as well
            _increment(thread_user_id, course_id, 'num_comments_generated')


@receiver(thread_followed)
def thread_follow_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    user_id = getattr(thread, 'user_id', None)
    action_user = kwargs['user']  # user who followed or un-followed thread

    if user_id and action_user.id != int(user_id):
        _increment(user_id, course_id, 'num_thread_followers')


@receiver(thread_unfollowed)
def thread_unfollow_signal_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Updates user social engagement score
    """
    thread = kwargs['post']
    course_id = getattr(thread, 'course_id', None)
    user_id = getattr(thread, 'user_id', None)
    action_user = kwargs['user']  # user who followed or un-followed thread

    if user_id and action_user.id != int(user_id):
        _decrement(user_id, course_id, 'num_thread_followers')


def _increment(*args, **kwargs):
    """
    A facade for handling incrementation.
    """
    task_handle_change_after_signal.delay(*args, **kwargs)


def _decrement(*args, **kwargs):
    """
    A facade for handling decrementation.
    """
    task_handle_change_after_signal.delay(*args, increment=False, **kwargs)
