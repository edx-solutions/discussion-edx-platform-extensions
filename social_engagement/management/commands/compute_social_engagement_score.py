"""
Command to compute social engagement score of users in a single course or all open courses
./manage.py lms compute_social_engagement_score -c {course_id} --settings=aws
./manage.py lms compute_social_engagement_score -a true --settings=aws
"""
import logging
import datetime
from pytz import UTC

from dateutil.relativedelta import relativedelta
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

    def add_arguments(self, parser):
        parser.add_argument(
            "-c",
            "--course_id",
            dest="course_id",
            help="course id to compute social engagement score",
            metavar="any/course/id"
        ),
        parser.add_argument(
            "-a",
            "--all",
            dest="compute_for_all_open_courses",
            help="set this to True if social scores for all open courses needs to be computed",
            metavar="True"
        ),
        parser.add_argument(
            "-i",
            "--inactive",
            dest="compute_for_inactive_courses",
            help="set this to True if social scores for inactive courses in the "
                 "past months needs to be computed",
            metavar="True"
        ),
        parser.add_argument(
            "-m",
            "--months_back_limit",
            dest="months_back_limit",
            type=int,
            default=0,
            help="set this to the number of months that the --inactive "
                 "parameter should look back to. Setting this to 0 will "
                 "compute scores from all archived courses. Example: "
                 "--months_back_limit=24 will compute social engagement scores "
                 "for inactive courses from the last 24 months.",
            metavar="0"
        ),
        parser.add_argument(
            "--noinput",
            "--no-input",
            dest="interactive",
            action="store_false",
            default=True,
            help="Do not prompt the user for input of any kind"
        ),

    def handle(self, *args, **options):
        course_id = options.get('course_id')
        compute_for_all_open_courses = options.get('compute_for_all_open_courses')
        compute_for_inactive_courses = options.get('compute_for_inactive_courses')
        months_back_limit = options.get('months_back_limit')
        interactive = options.get('interactive')

        if course_id:
            task_compute_social_scores_in_course.delay(course_id)
        elif compute_for_all_open_courses or compute_for_inactive_courses:
            # prompt for user confirmation in interactive mode
            execute = query_yes_no(
                "Are you sure to compute social engagement scores for all selected courses?"
                , default="no"
            ) if interactive else True

            if execute:
                courses = CourseOverview.objects.none()
                today = datetime.datetime.today().replace(tzinfo=UTC)

                # Add active courses to queryset if compute_for_all_open_courses is True
                if compute_for_all_open_courses:
                    courses |= CourseOverview.objects.filter(
                        Q(end__gte=today) |
                        Q(end__isnull=True)
                    )
                # Add inactive courses to queryset if compute_for_inactive_courses is True
                if compute_for_inactive_courses:
                    filter_set = Q(end__lt=today)
                    # If user set months back limit, add filter to queryset
                    if months_back_limit:
                        backwards_query_limit_date = (
                            datetime.datetime.today() - relativedelta(months=months_back_limit)
                        ).replace(tzinfo=UTC)
                        filter_set &= Q(end__gte=backwards_query_limit_date)
                    # Filter courses and add them to courses list
                    courses |= CourseOverview.objects.filter(filter_set)

                for course in courses:
                    course_id = unicode(course.id)
                    task_compute_social_scores_in_course.delay(course_id)
                    log.info("Task queued to compute social engagment score for course %s", course_id)
