"""
This module has implementation of celery tasks for discussion forum use cases
"""
import logging
import pytz
from datetime import datetime

from django.contrib.auth.models import User
from django.db import transaction
from celery.task import task

from student.models import CourseEnrollment
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey

from social_engagement.engagement import update_user_engagement_score, get_social_metric_points
from social_engagement.models import StudentSocialEngagementScore

log = logging.getLogger('edx.celery.task')


@task(name=u'lms.djangoapps.social_engagement.tasks.task_update_user_engagement_score')
def task_update_user_engagement_score(course_id, user_id):
    """
    Task to update user's engagement score
    """
    try:
        update_user_engagement_score(course_id, user_id)
    except Exception as exc:   # pylint: disable=broad-except
        log.info(
            "social engagement score update failure for course {} and user id {} with exception {}".format(
                course_id,
                user_id,
                repr(exc)
            )
        )


@task(name=u'lms.djangoapps.social_engagement.tasks.task_compute_social_scores_in_course')
def task_compute_social_scores_in_course(course_id):
    """
    Task to compute social scores in course
    """
    score_update_count = 0
    course_key = CourseKey.from_string(course_id)
    course = modulestore().get_course(course_key, depth=None)
    user_ids = CourseEnrollment.objects.values_list('user_id', flat=True).filter(
        is_active=1,
        course_id=course_key
    )

    if course:
        # For each user compute and save social engagement score
        for user_id in user_ids:
            update_user_engagement_score(
                course_key, user_id, compute_if_closed_course=True, course_descriptor=course
            )
            score_update_count += 1
    else:
        log.info("Course with course id %s does not exist", course_id)
    log.info("Social scores updated for %d users in course %s", score_update_count, course_id)


@task(name=u'lms.djangoapps.social_engagement.tasks.task_handle_change_after_signal')
def task_handle_change_after_signal(user_id, course_id, param, increment=True, items=1):
    """
    Save changes and calculate score.

    :param param: `str` with stat that should be changed or
                  `dict[str, int]` (`stat: number_of_occurrences`) with the stats that should be changed
    """
    factor = items if increment else -items
    social_metric_points = get_social_metric_points()
    course_key = CourseKey.from_string(course_id)

    # Do not calculate engagement after course ends.
    course_descriptor = modulestore().get_course(course_key)
    if course_descriptor and course_descriptor.end and course_descriptor.end < datetime.now(pytz.UTC):
        return

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        log.error("User with id: '{}' does not exist.".format(user_id))
    else:
        with transaction.atomic():
            score, _ = StudentSocialEngagementScore.objects.get_or_create(
                user=user,
                course_id=course_key,
            )
            if isinstance(param, dict):
                for key, value in param.items():
                    score.score += social_metric_points.get(key, 0) * factor * value

                    previous = getattr(score, key, 0)
                    setattr(score, key, previous + value * factor)
            else:
                score.score += social_metric_points.get(param, 0) * factor
                previous = getattr(score, param, 0)
                setattr(score, param, previous + factor)

            score.save()
