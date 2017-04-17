"""
Command to compute social engagement score of users in a course
./manage.py lms compute_social_engagement_score -c {course_id} --settings=aws
"""
import logging
from optparse import make_option

from django.core.management import BaseCommand

from social_engagement.engagement import update_user_engagement_score
from student.models import CourseEnrollment
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey

log = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Computes social engagement score of users in a course
    """
    help = "Command to compute social engagement score of users in a course"

    option_list = BaseCommand.option_list + (
        make_option(
            "-c",
            "--course_id",
            dest="course_id",
            help="course id to compute social engagement score",
            metavar="any/course/id"
        ),
    )

    def handle(self, *args, **options):
        score_update_count = 0
        course_id = options.get('course_id')
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
        log.info("Social scores updated for %d users", score_update_count)
