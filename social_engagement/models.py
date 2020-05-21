"""
Django database models supporting the social_engagement app
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, Sum
from django.dispatch import receiver
from django.db.models.signals import post_save

from model_utils.models import TimeStampedModel
from edx_solutions_api_integration.utils import invalid_user_data_cache, get_cached_data
from edx_solutions_api_integration.courses.utils import get_course_enrollment_count
from openedx.core.djangoapps.xmodule_django.models import CourseKeyField
from student.models import CourseEnrollment


class StudentSocialEngagementScore(TimeStampedModel):
    """
    StudentProgress is essentially a container used to store calculated progress of user
    """
    user = models.ForeignKey(User, db_index=True, null=False)
    course_id = CourseKeyField(db_index=True, max_length=255, blank=True, null=False)
    score = models.IntegerField(default=0, db_index=True, null=False)

    # stats
    num_threads = models.IntegerField(default=0)
    num_thread_followers = models.IntegerField(default=0)
    num_replies = models.IntegerField(default=0)
    num_flagged = models.IntegerField(default=0)
    num_comments = models.IntegerField(default=0)
    num_threads_read = models.IntegerField(default=0)
    num_downvotes = models.IntegerField(default=0)
    num_upvotes = models.IntegerField(default=0)
    num_comments_generated = models.IntegerField(default=0)

    class Meta:
        """
        Meta information for this Django model
        """
        unique_together = (('user', 'course_id'),)

    @property
    def stats(self):
        """
        Returns a dictionary containing all statistics.
        """
        return {
            stat: value
            for stat, value in self.__dict__.items()
            if stat.startswith('num_')
        }

    @classmethod
    def get_user_engagement_score(cls, course_key, user_id):
        """
        Returns the user's current engagement score or None
        if there is no record yet
        """

        try:
            entry = cls.objects.get(course_id__exact=course_key, user__id=user_id)
        except cls.DoesNotExist:
            return None

        return entry.score

    @classmethod
    def get_user_engagements_stats(cls, course_key, user_id, default=None):
        """
        Returns user's statistics as a dictionary.
        If record does not exist, it returns `default` if specified
        or else a dictionary containing statistics with their default values.
        """
        try:
            return cls.objects.get(course_id__exact=course_key, user__id=user_id).stats
        except cls.DoesNotExist:
            if default is not None:
                return default

            return {
                stat.name: stat.default
                for stat in cls._meta.fields
                if stat.name.startswith('num_')
            }

    @classmethod
    def get_course_average_engagement_score(cls, course_key, exclude_users=None):
        """
        Returns the course average engagement score.
        """
        course_id = course_key.to_deprecated_string()
        data = get_cached_data('social', course_id)
        if data is not None:
            return data.get('course_avg')

        exclude_users = exclude_users or []
        queryset = cls.objects.select_related('user').filter(
            course_id__exact=course_key,
            user__is_active=True,
            user__courseenrollment__is_active=True,
            user__courseenrollment__course_id__exact=course_key
        )
        queryset = queryset.exclude(user__id__in=exclude_users)
        aggregates = queryset.aggregate(Sum('score'))
        avg_score = 0
        total_score = aggregates['score__sum']
        if total_score is None:
            total_score = 0
        if total_score:
            user_count = get_course_enrollment_count(course_id)
            if user_count:
                avg_score = int(round(total_score / float(user_count)))

        return avg_score

    @classmethod
    def _get_course_engagement(cls, course_key, organization=None, exclude_users=None, stats=False):
        """
        Helper for getting a dictionary containing data about users in a course in form of `user_id: attr`.
        """
        exclude_users = exclude_users or []
        queryset = cls.objects\
            .filter(course_id=course_key)\
            .exclude(user__id__in=exclude_users)\
            .prefetch_related('user')

        if organization:
            queryset = queryset.filter(user__organizations=organization)

        attr = 'stats' if stats else 'score'
        return {
            stat.user.id: getattr(stat, attr)
            for stat in queryset
        }

    @classmethod
    def get_course_engagement_scores(cls, course_key, organization=None, exclude_users=None):
        """
        Returns a dictionary containing data about users in a course in form of `user_id: stats`.
        """
        return cls._get_course_engagement(course_key, organization, exclude_users)

    @classmethod
    def get_course_engagement_stats(cls, course_key, organization=None, exclude_users=None):
        """
        Returns a dictionary containing data about users in a course in form of `user_id: stats`.
        """
        return cls._get_course_engagement(course_key, organization, exclude_users, stats=True)

    @classmethod
    def save_user_engagement_score(cls, course_key, user_id, score, stats=None):
        """
        Creates or updates an engagement score
        """
        stats = stats or {}
        cls.objects.update_or_create(
            course_id=course_key,
            user_id=user_id,
            defaults=dict(score=score, **stats)
        )

    @classmethod
    def get_user_leaderboard_position(cls, course_key, **kwargs):
        """
        Returns user's progress position and completions for a given course.
        :param kwargs:
            - `user_id`
            - `exclude_users`
            - `group_ids`
            - `org_ids`
            - `cohort_user_ids`

        :returns data = {"score": 22, "position": 4}
        """
        data = {"score": 0, "position": 0}
        try:
            queryset = cls.objects.get(course_id__exact=course_key, user__id=kwargs.get('user_id'))
        except cls.DoesNotExist:
            queryset = None

        if queryset:
            user_score = queryset.score
            user_time_scored = queryset.created

            queryset = cls._build_queryset(course_key, **kwargs)

            users_above = queryset.filter(
                Q(score__gt=user_score) |
                Q(score=user_score, modified__lt=user_time_scored)
            ).count()

            data['position'] = users_above + 1 if user_score > 0 else 0
            data['score'] = user_score
        return data

    @classmethod
    def generate_leaderboard(cls, course_key, **kwargs):
        """
        Assembles a data set representing the Top N users, by progress, for a given course.
        :param kwargs:
            - `count`
            - `exclude_users`
            - `group_ids`
            - `org_ids`
            - `cohort_user_ids`

        :returns data = [
            {'id': 123, 'username': 'testuser1', 'title', 'Engineer', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'score': 80},
            {'id': 983, 'username': 'testuser2', 'title', 'Analyst', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'score': 70},
            {'id': 246, 'username': 'testuser3', 'title', 'Product Owner', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'score': 62},
            {'id': 357, 'username': 'testuser4', 'title', 'Director', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'completions': 58},
        ]

        """
        data = {
            'course_avg': 0,
            'total_user_count': 0,
            'queryset': [],
        }
        course_id = course_key.to_deprecated_string()
        queryset = cls._build_queryset(course_key, **kwargs)

        if not kwargs.get('cohort_user_ids'):
            data['total_user_count'] = get_course_enrollment_count(course_id)
            data = get_cached_data('social', course_id)
            if data is not None:
                data['course_avg'] = data.get('course_avg')
            else:
                data['course_avg'] = cls._calculate_course_average_engagement_score(queryset, data['total_user_count'])
        else:
            data['total_user_count'] = cls._build_enrollment_queryset(
                course_key,
                exclude_users=kwargs.get('exclude_users'),
                cohort_user_ids=kwargs.get('cohort_user_ids'),
            ).count()
            data['course_avg'] = cls._calculate_course_average_engagement_score(queryset, data['total_user_count'])

        if kwargs.get('count'):
            data['queryset'] = queryset.values(
                'user__id',
                'user__username',
                'user__first_name',
                'user__last_name',
                'user__profile__title',
                'user__profile__profile_image_uploaded_at',
                'score',
                'modified'
            ).order_by('-score', 'modified')[:kwargs.get('count')]
        else:
            data['queryset'] = queryset

        return data

    @classmethod
    def _build_queryset(cls, course_key, **kwargs):
        """
        Helper method to return filtered queryset.
        :param kwargs:
            - `exclude_users`
            - `group_ids`
            - `org_ids`
            - `cohort_user_ids`
        """
        queryset = cls.objects.filter(
            course_id__exact=course_key,
            user__is_active=True,
            user__courseenrollment__is_active=True,
            user__courseenrollment__course_id__exact=course_key,
        ).exclude(
            user__in=kwargs.get('exclude_users') or []
        )

        if kwargs.get('group_ids'):
            queryset = queryset.filter(user__groups__in=kwargs.get('group_ids')).distinct()

        if kwargs.get('org_ids'):
            queryset = queryset.filter(user__organizations__in=kwargs.get('org_ids'))

        if kwargs.get('cohort_user_ids'):
            queryset = queryset.filter(user_id__in=kwargs.get('cohort_user_ids'))

        return queryset

    @classmethod
    def _build_enrollment_queryset(cls, course_key, **kwargs):
        """
        Helper method to return filtered enrollment queryset.
        :param kwargs:
            - `exclude_users`
            - `group_ids`
            - `org_ids`
            - `cohort_user_ids`
        """
        queryset = CourseEnrollment.objects.users_enrolled_in(course_key)\
            .exclude(id__in=kwargs.get('exclude_users') or [])

        if kwargs.get('group_ids'):
            queryset = queryset.filter(groups__in=kwargs.get('group_ids')).distinct()

        if kwargs.get('org_ids'):
            queryset = queryset.filter(organizations__in=kwargs.get('org_ids'))

        if kwargs.get('cohort_user_ids'):
            queryset = queryset.filter(id__in=kwargs.get('cohort_user_ids'))

        return queryset

    @classmethod
    def _calculate_course_average_engagement_score(cls, queryset, total_user_count):
        """
        Helper method to calculate and return course average score from queryset.
        """
        aggregates = queryset.aggregate(Sum('score'))
        total_score = aggregates['score__sum'] if aggregates['score__sum'] else 0
        if total_score:
            return int(round(total_score / float(total_user_count)))
        return 0

class StudentSocialEngagementScoreHistory(TimeStampedModel):
    """
    A running audit trail for the StudentProgress model.  Listens for
    post_save events and creates/stores copies of progress entries.
    """
    user = models.ForeignKey(User, db_index=True)
    course_id = CourseKeyField(db_index=True, max_length=255, blank=True)
    score = models.IntegerField()


@receiver(post_save, sender=StudentSocialEngagementScore)
def on_studentengagementscore_save(sender, instance, created, **kwargs):
    """
    When a studentengagementscore is saved, we want to also store the
    score value in the history table, so we have a complete history
    of the student's engagement score
    """
    instance.refresh_from_db()
    invalid_user_data_cache('social', instance.course_id, instance.user.id)
    history_entry = StudentSocialEngagementScoreHistory(
        user=instance.user,
        course_id=instance.course_id,
        score=instance.score
    )
    history_entry.save()
