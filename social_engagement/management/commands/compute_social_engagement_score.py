"""
Command to compute social engagement score of users in a single course or all open courses
./manage.py lms compute_social_engagement_score -c {course_id} --settings=aws
./manage.py lms compute_social_engagement_score -a true --settings=aws
"""
import logging
import datetime
from pytz import UTC
from optparse import make_option

from django.core.management import BaseCommand
from django.db.models import Q

from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from util.prompt import query_yes_no
from social_engagement.tasks import task_compute_social_scores_in_course

log = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Computes social engagement score of users in a single course or all open courses
    """
    help = "Command to compute social engagement score of users in a single course or all open courses"

    option_list = BaseCommand.option_list + (
        make_option(
            "-c",
            "--course_id",
            dest="course_id",
            help="course id to compute social engagement score",
            metavar="any/course/id"
        ),
        make_option(
            "-a",
            "--all",
            dest="compute_for_all_open_courses",
            help="set this to True if social scores for all open courses needs to be computed",
            metavar="True"
        ),
        make_option(
            "--noinput",
            "--no-input",
            dest="interactive",
            action="store_false",
            default=True,
            help="Do not prompt the user for input of any kind",
            metavar="True"
        ),
    )

    def handle(self, *args, **options):
        course_id = options.get('course_id')
        compute_for_all_open_courses = options.get('compute_for_all_open_courses')
        interactive = options.get('interactive')

        if course_id:
            task_compute_social_scores_in_course.delay(course_id)
        elif compute_for_all_open_courses:
            # prompt for user confirmation in interactive mode
            execute = query_yes_no(
                "Are you sure to compute social engagement scores for all open courses?"
                , default="no"
            ) if interactive else True

            if execute:
                open_courses = CourseOverview.objects.filter(
                    Q(end__gte=datetime.datetime.today().replace(tzinfo=UTC)) |
                    Q(end__isnull=True)
                )
                for course in open_courses:
                    course_id = unicode(course.id)
                    task_compute_social_scores_in_course.delay(course_id)
                    log.info("Task queued to compute social engagment score for course %s", course_id)
