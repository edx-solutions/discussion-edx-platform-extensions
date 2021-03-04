"""
This module has implementation of celery tasks for discussion forum use cases
"""
import logging
from datetime import datetime

import pytz
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import F

from celery.task import task
from opaque_keys.edx.keys import CourseKey
from social_engagement.engagement import (get_social_metric_points,
                                          update_course_engagement)
from social_engagement.models import StudentSocialEngagementScore
from xmodule.modulestore.django import modulestore

log = logging.getLogger('edx.celery.task')


@task(
    name='lms.djangoapps.social_engagement.tasks.task_compute_social_scores_in_course',
    routing_key=settings.RECALCULATE_SOCIAL_ENGAGEMENT_ROUTING_KEY,
)
def task_compute_social_scores_in_course(course_id):
    """
    Task to compute social scores in course
    """
    course_key = CourseKey.from_string(course_id)
    course = modulestore().get_course(course_key, depth=None)

    if course:
        score_update_count = update_course_engagement(
            course_key, compute_if_closed_course=True, course_descriptor=course
        )
        log.info("Social scores updated for %d users in course %s", score_update_count or 0, course_id)

    else:
        log.info("Course with course id %s does not exist", course_id)


@task(name='lms.djangoapps.social_engagement.tasks.task_update_user_engagement')
def task_update_user_engagement(user_id, course_id, param, increment=True, items=1):
    """
    Save changes in stats and calculate score.

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
        score, _ = StudentSocialEngagementScore.objects.get_or_create(
            user=user,
            course_id=course_key,
        )
        if isinstance(param, dict):
            score_difference = 0
            for key, value in param.items():
                score_difference += social_metric_points.get(key, 0) * factor * value
                setattr(score, key, F(key) + value * factor)
            score.score = F('score') + score_difference
        else:
            score.score = F('score') + social_metric_points.get(param, 0) * factor
            setattr(score, param, F(param) + factor)

        score.save()
