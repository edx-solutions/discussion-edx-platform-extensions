"""
Business logic tier regarding social engagement scores
"""

import sys
from datetime import datetime

import lms.lib.comment_client as cc
import logging
import pytz
from collections import defaultdict
from discussion_api.exceptions import CommentNotFoundError, ThreadNotFoundError
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.http import HttpRequest
from edx_notifications.data import NotificationMessage
from edx_notifications.lib.publisher import (
    publish_notification_to_user,
    get_notification_type
)
from edx_solutions_api_integration.utils import (
    get_aggregate_exclusion_user_ids,
)
from lms.lib.comment_client.user import get_user_social_stats
from lms.lib.comment_client.utils import CommentClientRequestError
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from requests.exceptions import ConnectionError
from student.models import CourseEnrollment
from xmodule.modulestore.django import modulestore

from .models import StudentSocialEngagementScore

log = logging.getLogger(__name__)


def update_user_engagement_score(course_id, user_id, compute_if_closed_course=False, course_descriptor=None):
    """
    Compute the user's Engagement Score and store it in the
    database. We will not update the record, if the score
    is the same as it currently exists
    """

    if not settings.FEATURES.get('ENABLE_SOCIAL_ENGAGEMENT', False):
        return

    course_key = course_id if isinstance(course_id, CourseKey) else CourseKey.from_string(course_id)

    if not course_descriptor:
        # it course descriptor was not passed in (as an optimization)
        course_descriptor = modulestore().get_course(course_key)

    if not course_descriptor:
        # couldn't find course?!?
        return

    if not compute_if_closed_course and course_descriptor.end:
        # if course is closed then don't bother. Note
        # we can override this if we want to force
        # update
        now_utc = datetime.now(pytz.UTC)
        if now_utc > course_descriptor.end:
            log.info('update_user_engagement_score() is skipping because the course is closed...')
            return

    previous_score = StudentSocialEngagementScore.get_user_engagement_score(course_key, user_id) or 0

    try:
        log.info('Updating social engagement score for user_id {}  in course_key {}'.format(user_id, course_key))

        # cs_comment_service works is slash separated course_id strings
        slash_course_id = course_key.to_deprecated_string()

        # get the course social stats, passing along a course end date to remove any activity after the course
        # closure from the stats. Note that we are calling out to the cs_comment_service
        # and so there might be a HTTP based communication error

        social_stats = _get_user_social_stats(user_id, slash_course_id, course_descriptor.end)
        _update_current_data(user_id, course_id, social_stats)

        if social_stats:
            current_score = _compute_social_engagement_score(social_stats)

            log.info('previous_score = {}  current_score = {}'.format(previous_score, current_score))

            if current_score != previous_score:
                StudentSocialEngagementScore.save_user_engagement_score(course_key, user_id, current_score)

    except (CommentClientRequestError, ConnectionError), error:
        log.exception(error)


def get_social_metric_points():
    """
    Get custom or default social metric points.
    """
    # we can override this in configuration, but this
    # is default values
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


def _get_user_social_stats(user_id, slash_course_id, end_date):
    """
    Helper function which basically calls into the cs_comment_service. We wrap this,
    to make it easier to write mock functions for unit testing
    """

    stats = get_user_social_stats(user_id, slash_course_id, end_date=end_date)
    log.debug('raw stats = {}'.format(stats))
    # the comment service returns the user_id as a string
    user_id_str = str(user_id)
    if user_id_str in stats:
        return stats[user_id_str]
    else:
        return None


def _update_current_data(user_id, course_id, social_stats):
    """
    Store data from API.
    """
    score = StudentSocialEngagementScore.objects.get(user__id=user_id, course_id=course_id)
    for key, val in social_stats.iteritems():
        setattr(score, key, val)

    score.save()


def _compute_social_engagement_score(social_metrics):
    """
    For a list of social_stats, compute the social score
    """

    # we can override this in configuration, but this
    # is default values
    social_metric_points = get_social_metric_points()

    social_total = 0
    for key, val in social_metric_points.iteritems():
        social_total += social_metrics.get(key, 0) * val

    return social_total


def update_course_engagement_scores(course_id, compute_if_closed_course=False, course_descriptor=None):
    """
    Iterate over all active course enrollments and update the
    students engagement scores
    """

    course_key = course_id if isinstance(course_id, CourseKey) else CourseKey.from_string(course_id)

    if not course_descriptor:
        # pre-fetch course descriptor, so we don't have to refetch later
        # over and over again
        course_descriptor = modulestore().get_course(course_key)

    if not course_descriptor:
        return

    user_ids = CourseEnrollment.objects.values_list('user_id', flat=True).filter(
        is_active=1,
        course_id=course_key
    )

    for user_id in user_ids:
        update_user_engagement_score(course_key, user_id, compute_if_closed_course=compute_if_closed_course, course_descriptor=course_descriptor)


def update_all_courses_engagement_scores(compute_if_closed_course=False):
    """
    Iterates over all courses in the modelstore and computes engagment
    scores for all enrolled students
    """

    courses = modulestore().get_courses()

    for course in courses:
        update_course_engagement_scores(
            course.id,
            compute_if_closed_course=compute_if_closed_course,
            course_descriptor=course
        )


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
            instance.user.id,
            get_aggregate_exclusion_user_ids(instance.course_id)
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
            instance.user.id,
            get_aggregate_exclusion_user_ids(instance.course_id)
        )['position']

        if leaderboard_rank == 0:
            # quick escape when user is not in the leaderboard
            # which means rank = 0. Trouble is 0 < 3, so unfortunately
            # the semantics around 0 don't match the logic below
            return

        # logic for Notification trigger is when a user enters into the Leaderboard
        leaderboard_size = getattr(settings, 'LEADERBOARD_SIZE', 3)
        presave_leaderboard_rank = instance.presave_leaderboard_rank if instance.presave_leaderboard_rank else sys.maxint
        if leaderboard_rank <= leaderboard_size and presave_leaderboard_rank > leaderboard_size:
            try:
                notification_msg = NotificationMessage(
                    msg_type=get_notification_type(u'open-edx.lms.leaderboard.engagement.rank-changed'),
                    namespace=unicode(instance.course_id),
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
                    'course_id': unicode(instance.course_id),
                })

                publish_notification_to_user(int(instance.user.id), notification_msg)
            except Exception, ex:
                # Notifications are never critical, so we don't want to disrupt any
                # other logic processing. So log and continue.
                log.exception(ex)


def get_involved_users_in_thread(request, thread):
    """
    Compute all the users involved in the children of a specific thread.
    """
    params = {"thread_id": thread.id, "page_size": 100}
    is_question = True if getattr(thread, "thread_type", None) == "question" else False
    author_id = getattr(thread, 'username', None)
    if hasattr(thread, 'username'):
        author_id = thread.user_id

    results = _detail_results_factory()

    if is_question:
        # get users of the non-endorsed comments in thread
        params.update({"endorsed": False})
        _get_thread_details_for_deletion(_get_request(request, params), results)
        # get users of the endorsed comments in thread
        params.update({"endorsed": True})
        _get_thread_details_for_deletion(_get_request(request, params), results)
    else:
        _get_thread_details_for_deletion(_get_request(request, params), results)

    users = results['users']
    for user, _ in users.items():
        id_ = int(User.objects.get(username=user).id)
        users[id_] = users[user]
        del users[user]

    if author_id:
        users[author_id]['num_upvotes'] += thread.votes.get('count', 0)
        users[author_id]['num_threads'] += 1
        users[author_id]['num_comments_generated'] += results['all_comments']
        users[author_id]['num_thread_followers'] += thread.get_num_followers()

    return users


def get_involved_users_in_comment(request, comment):
    """
    Method used to extract the involved users in the comment.
    This method also returns the creator of the post.
    """
    author_id = None
    if hasattr(comment, 'parent_id'):
        author_id = _get_author_of_comment(comment.parent_id)
    if hasattr(comment, 'thread_id'):
        author_id = _get_author_of_thread(comment.thread_id)

    results = _get_comment_details_for_deletion(request, comment.id)
    users = results['users']
    for user, _ in users.items():
        id_ = int(User.objects.get(username=user).id)
        users[id_] = users[user]
        del users[user]
    if author_id:
        users[int(author_id)]['num_replies'] += results['replies']

    return users


def _get_users_in_thread(request):
    from lms.djangoapps.discussion_api.views import CommentViewSet
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
    from lms.djangoapps.discussion_api.views import CommentViewSet
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


def _get_thread_details_for_deletion(request, results):
    """
    Get details of thread and related users that are required for deletion purposes.
    """
    from lms.djangoapps.discussion_api.views import CommentViewSet
    response_page = 1
    has_results = True
    while has_results:
        try:
            response = CommentViewSet().list(_get_request(request, {"page": response_page}))
            if response_page == 1:
                results['all_comments'] += response.data['pagination']['count']

            for comment in response.data["results"]:
                results['users'][comment['author']]['num_comments'] += 1
                results['users'][comment['author']]['num_upvotes'] += comment['vote_count']

                if comment['child_count'] > 0:
                    _get_comment_details_for_deletion(request, comment['id'], results, nested=True)

            has_results = response.data["pagination"]["next"]
            response_page += 1
        except (ThreadNotFoundError, InvalidKeyError):
            return results
    return results


def _get_comment_details_for_deletion(request, comment_id, results=None, nested=True):
    """
    Get details of comment and related users that are required for deletion purposes.
    """
    from lms.djangoapps.discussion_api.views import CommentViewSet
    if not results:
        results = _detail_results_factory()

    response_page = 1
    has_results = True
    while has_results:
        try:
            response = CommentViewSet().retrieve(_get_request(request, {"page": response_page}), comment_id)
            if results['replies'] == 0:
                results['replies'] = response.data['pagination']['count']

            if response_page == 1:
                results['all_comments'] += response.data['pagination']['count']

            for comment in response.data["results"]:
                if not nested:
                    results['users'][comment['author']]['num_comments'] += 1
                else:
                    results['users'][comment['author']]['num_replies'] += 1
                results['users'][comment['author']]['num_upvotes'] += comment['vote_count']

                if comment['child_count'] > 0:
                    _get_comment_details_for_deletion(request, comment['id'], results, nested=True)

            has_results = response.data["pagination"]["next"]
            response_page += 1
        except (CommentNotFoundError, InvalidKeyError):
            return results
    return results


def _detail_results_factory():
    return {
        'replies': 0,
        'all_comments': 0,
        'users': defaultdict(lambda: defaultdict(int)),
    }
