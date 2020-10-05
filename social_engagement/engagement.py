"""
Business logic tier regarding social engagement scores
"""

import logging
import sys
from collections import defaultdict
from datetime import datetime

import pytz
from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.http import HttpRequest

import openedx.core.djangoapps.django_comment_common.comment_client as cc
from edx_notifications.data import NotificationMessage
from edx_notifications.lib.publisher import (get_notification_type,
                                             publish_notification_to_user)
from edx_solutions_api_integration.utils import get_aggregate_exclusion_user_ids
from lms.djangoapps.discussion.rest_api.exceptions import (CommentNotFoundError,
                                                      ThreadNotFoundError)
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.django_comment_common.comment_client.user import get_course_social_stats
from openedx.core.djangoapps.django_comment_common.comment_client.utils import CommentClientRequestError
from requests.exceptions import ConnectionError
from xmodule.modulestore.django import modulestore

from .models import StudentSocialEngagementScore

log = logging.getLogger(__name__)


def update_course_engagement(course_id, compute_if_closed_course=False, course_descriptor=None):
    """
    Compute and save engagement scores and stats for whole course.
    """

    if not settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT', False):
        return

    course_key = course_id if isinstance(course_id, CourseKey) else CourseKey.from_string(course_id)
    # cs_comment_service works is slash separated course_id strings
    slash_course_id = course_key.to_deprecated_string()

    if not course_descriptor:
        # it course descriptor was not passed in (as an optimization)
        course_descriptor = modulestore().get_course(course_key)

    if not course_descriptor:
        # couldn't find course?!?
        return

    if not compute_if_closed_course and course_descriptor.end:
        # if course is closed then don't bother. Note we can override this if we want to force update
        now_utc = datetime.now(pytz.UTC)
        if now_utc > course_descriptor.end:
            log.info('update_user_engagement_score() is skipping because the course is closed...')
            return

    score_update_count = 0

    try:
        for user_id, social_stats in _get_course_social_stats(slash_course_id):
            log.info('Updating social engagement score for user_id {}  in course_key {}'.format(user_id, course_key))

            current_score = _compute_social_engagement_score(social_stats)

            StudentSocialEngagementScore.save_user_engagement_score(
                course_key, user_id, current_score, social_stats
            )

            score_update_count += 1

    except (CommentClientRequestError, ConnectionError) as error:
        log.exception(error)

    return score_update_count


def _get_course_social_stats(course_id):
    """"
    Yield user and user's stats for whole course from Forum API.
    """
    stats = get_course_social_stats(course_id)
    yield from stats.items()


def get_social_metric_points():
    """
    Get custom or default social metric points.
    """
    return getattr(
        settings,
        'SOCIAL_METRIC_POINTS',
        {
            'num_threads': 10,
            'num_comments': 15,
            'num_replies': 15,
            'num_upvotes': 25,
            'num_thread_followers': 5,
            'num_comments_generated': 15,
        }
    )


def _compute_social_engagement_score(social_metrics):
    """
    For a list of social_stats, compute the social score
    """
    social_metric_points = get_social_metric_points()

    social_total = 0
    for key, val in social_metric_points.items():
        social_total += social_metrics.get(key, 0) * val

    return social_total


#
# Support for Notifications, these two receivers should actually be migrated into a new Leaderboard django app.
# For now, put the business logic here, but it is pretty decoupled through event signaling
# so we should be able to move these files easily when we are able to do so
#
@receiver(pre_save, sender=StudentSocialEngagementScore)
def handle_progress_pre_save_signal(sender, instance, **kwargs):
    """
    Handle the pre-save ORM event on StudentSocialEngagementScore
    """

    if settings.FEATURES['ENABLE_NOTIFICATIONS']:
        # If notifications feature is enabled, then we need to get the user's
        # rank before the save is made, so that we can compare it to
        # after the save and see if the position changes

        instance.presave_leaderboard_rank = StudentSocialEngagementScore.get_user_leaderboard_position(
            instance.course_id,
            user_id=instance.user.id,
            exclude_users=get_aggregate_exclusion_user_ids(instance.course_id)
        )['position']


@receiver(post_save, sender=StudentSocialEngagementScore)
def handle_progress_post_save_signal(sender, instance, **kwargs):
    """
    Handle the pre-save ORM event on CourseModuleCompletions
    """

    if settings.FEATURES['ENABLE_NOTIFICATIONS']:
        # If notifications feature is enabled, then we need to get the user's
        # rank before the save is made, so that we can compare it to
        # after the save and see if the position changes

        leaderboard_rank = StudentSocialEngagementScore.get_user_leaderboard_position(
            instance.course_id,
            user_id=instance.user.id,
            exclude_users=get_aggregate_exclusion_user_ids(instance.course_id)
        )['position']

        if leaderboard_rank == 0:
            # quick escape when user is not in the leaderboard
            # which means rank = 0. Trouble is 0 < 3, so unfortunately
            # the semantics around 0 don't match the logic below
            return

        # logic for Notification trigger is when a user enters into the Leaderboard
        leaderboard_size = getattr(settings, 'LEADERBOARD_SIZE', 3)
        presave_leaderboard_rank = instance.presave_leaderboard_rank if instance.presave_leaderboard_rank else sys.maxsize
        if leaderboard_rank <= leaderboard_size and presave_leaderboard_rank > leaderboard_size:
            try:
                notification_msg = NotificationMessage(
                    msg_type=get_notification_type('open-edx.lms.leaderboard.engagement.rank-changed'),
                    namespace=str(instance.course_id),
                    payload={
                        '_schema_version': '1',
                        'rank': leaderboard_rank,
                        'leaderboard_name': 'Engagement',
                    }
                )

                #
                # add in all the context parameters we'll need to
                # generate a URL back to the website that will
                # present the new course announcement
                #
                # IMPORTANT: This can be changed to msg.add_click_link() if we
                # have a particular URL that we wish to use. In the initial use case,
                # we need to make the link point to a different front end website
                # so we need to resolve these links at dispatch time
                #
                notification_msg.add_click_link_params({
                    'course_id': str(instance.course_id),
                })

                publish_notification_to_user(int(instance.user.id), notification_msg)
            except Exception as ex:
                # Notifications are never critical, so we don't want to disrupt any
                # other logic processing. So log and continue.
                log.exception(ex)


def get_involved_users_in_thread(request, thread):
    """
    Compute all the users involved in the children of a specific thread.
    """
    params = {"thread_id": thread.id, "page_size": 100}
    is_question = getattr(thread, "thread_type", None) == "question"
    author_id = getattr(thread, 'user_id', None)
    results = _detail_results_factory()

    if is_question:
        # get users of the non-endorsed comments in thread
        params.update({"endorsed": False})
        _get_details_for_deletion(_get_request(request, params), results=results, is_thread=True)
        # get users of the endorsed comments in thread
        if getattr(thread, 'has_endorsed', False):
            params.update({"endorsed": True})
            _get_details_for_deletion(_get_request(request, params), results=results, is_thread=True)
    else:
        _get_details_for_deletion(_get_request(request, params), results=results, is_thread=True)

    users = results['users']

    if author_id:
        users[author_id]['num_upvotes'] += thread.votes.get('count', 0)
        users[author_id]['num_threads'] += 1
        users[author_id]['num_comments_generated'] += results['all_comments']
        users[author_id]['num_thread_followers'] += thread.get_num_followers()
        if thread.abuse_flaggers:
            users[author_id]['num_flagged'] += 1

    return users


def get_involved_users_in_comment(request, comment):
    """
    Method used to extract the involved users in the comment.
    This method also returns the creator of the post.
    """
    params = {"page_size": 100}
    comment_author_id = getattr(comment, 'user_id', None)
    thread_author_id = None
    if hasattr(comment, 'thread_id'):
        thread_author_id = _get_author_of_thread(comment.thread_id)

    results = _get_details_for_deletion(_get_request(request, params), comment.id, nested=True)
    users = results['users']

    if comment_author_id:
        users[comment_author_id]['num_upvotes'] += comment.votes.get('count', 0)

        if getattr(comment, 'parent_id', None):
            # It's a reply.
            users[comment_author_id]['num_replies'] += 1
        else:
            # It's a comment.
            users[comment_author_id]['num_comments'] += 1

        if comment.abuse_flaggers:
            users[comment_author_id]['num_flagged'] += 1

    if thread_author_id:
        users[thread_author_id]['num_comments_generated'] += results['replies'] + 1

    return users


def _detail_results_factory():
    """
    Helper method to maintain organized result structure while getting involved users.
    """
    return {
        'replies': 0,
        'all_comments': 0,
        'users': defaultdict(lambda: defaultdict(int)),
    }


def _get_users_in_thread(request):
    from lms.djangoapps.discussion.rest_api.views import CommentViewSet
    users = set()
    response_page = 1
    has_results = True
    while has_results:
        try:
            params = {"page": response_page}
            response = CommentViewSet().list(
                _get_request(request, params)
            )

            for comment in response.data["results"]:
                users.add(comment["author"])
                if comment["child_count"] > 0:
                    users.update(_get_users_in_comment(request, comment["id"]))
            has_results = response.data["pagination"]["next"]
            response_page += 1
        except (ThreadNotFoundError, InvalidKeyError):
            return users
    return users


def _get_users_in_comment(request, comment_id):
    from lms.djangoapps.discussion.rest_api.views import CommentViewSet
    users = set()
    response_page = 1
    has_results = True
    while has_results:
        try:
            response = CommentViewSet().retrieve(_get_request(request, {"page": response_page}), comment_id)
            for comment in response.data["results"]:
                users.add(comment["author"])
                if comment["child_count"] > 0:
                    users.update(_get_users_in_comment(request, comment["id"]))
            has_results = response.data["pagination"]["next"]
            response_page += 1
        except (ThreadNotFoundError, InvalidKeyError):
            return users
    return users


def _get_request(incoming_request, params):
    request = HttpRequest()
    request.method = 'GET'
    request.user = incoming_request.user
    request.META = incoming_request.META.copy()
    request.GET = incoming_request.GET.copy()
    request.GET.update(params)
    return request


def _get_author_of_comment(parent_id):
    comment = cc.Comment.find(parent_id)
    if comment and hasattr(comment, 'user_id'):
        return comment.user_id


def _get_author_of_thread(thread_id):
    thread = cc.Thread.find(thread_id)
    if thread and hasattr(thread, 'user_id'):
        return thread.user_id


def _get_details_for_deletion(request, comment_id=None, results=None, nested=False, is_thread=False):
    """
    Get details of comment or thread and related users that are required for deletion purposes.
    """
    if not results:
        results = _detail_results_factory()

    for page, response in enumerate(_get_paginated_results(request, comment_id, is_thread)):
            if page == 0:
                results['all_comments'] += response.data['pagination']['count']

            if results['replies'] == 0:
                results['replies'] = response.data['pagination']['count']

            for comment in response.data['results']:
                _extract_stats_from_comment(request, comment, results, nested)

    return results


def _get_paginated_results(request, comment_id, is_thread):
    """
    Yield paginated comments of comment or thread.
    """
    from lms.djangoapps.discussion.rest_api.views import CommentViewSet

    response_page = 1
    has_next = True
    while has_next:
        try:
            if is_thread:
                response = CommentViewSet().list(_get_request(request, {"page": response_page}))
            else:
                response = CommentViewSet().retrieve(_get_request(request, {"page": response_page}), comment_id)
        except (ThreadNotFoundError, CommentNotFoundError, InvalidKeyError):
            raise StopIteration

        has_next = response.data["pagination"]["next"]
        response_page += 1
        yield response


def _extract_stats_from_comment(request, comment, results, nested):
    """
    Extract results from comment and its nested comments.
    """
    user_id = comment.serializer.instance['user_id']

    if not nested:
        results['users'][user_id]['num_comments'] += 1
    else:
        results['users'][user_id]['num_replies'] += 1
    results['users'][user_id]['num_upvotes'] += comment['vote_count']
    if comment.serializer.instance['abuse_flaggers']:
        results['users'][user_id]['num_flagged'] += 1

    if comment['child_count'] > 0:
        _get_details_for_deletion(request, comment['id'], results, nested=True)
