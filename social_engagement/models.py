"""
Django database models supporting the social_engagement app
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, Sum
from django.dispatch import receiver
from django.db.models.signals import post_save

from model_utils.models import TimeStampedModel
from edx_solutions_api_integration.utils import (
    invalid_user_data_cache,
)
from student.models import CourseEnrollment
from openedx.core.djangoapps.xmodule_django.models import CourseKeyField
from student.models import CourseEnrollment


class StudentSocialEngagementScore(TimeStampedModel):
    """
    StudentProgress is essentially a container used to store calculated progress of user
    """
    user = models.ForeignKey(User, db_index=True, null=False)
    course_id = CourseKeyField(db_index=True, max_length=255, blank=True, null=False)
    score = models.IntegerField(default=0, db_index=True, null=False)

    class Meta:
        """
        Meta information for this Django model
        """
        unique_together = (('user', 'course_id'),)

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
    def get_course_average_engagement_score(cls, course_key, exclude_users=None):
        """
        Returns the course average engagement score.
        """
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
            user_count = CourseEnrollment.objects.users_enrolled_in(course_key).exclude(id__in=exclude_users).count()
            if user_count:
                avg_score = int(round(total_score / float(user_count)))

        return avg_score

    @classmethod
    def save_user_engagement_score(cls, course_key, user_id, score):
        """
        Creates or updates an engagement score
        """
        cls.objects.update_or_create(
            course_id=course_key,
            user_id=user_id,
            defaults={
                "score": score,
            }
        )

    @classmethod
    def get_user_leaderboard_position(cls, course_key, user_id, exclude_users=None):
        """
        Returns user's progress position and completions for a given course.
        data = {"score": 22, "position": 4}
        """
        data = {"score": 0, "position": 0}
        try:
            queryset = cls.objects.get(course_id__exact=course_key, user__id=user_id)
        except cls.DoesNotExist:
            queryset = None

        if queryset:
            user_score = queryset.score
            user_time_scored = queryset.created

            query = cls.objects.select_related('user').filter(
                Q(score__gt=user_score) | Q(score=user_score, modified__lt=user_time_scored),
                course_id__exact=course_key,
                user__is_active=True,
                user__courseenrollment__is_active=True,
                user__courseenrollment__course_id__exact=course_key,
            )

            if exclude_users:
                query = query.exclude(user__id__in=exclude_users)

            users_above = query.count()
            data['position'] = users_above + 1 if user_score > 0 else 0
            data['score'] = user_score
        return data

    @classmethod
    def generate_leaderboard(cls, course_key, count=3, exclude_users=None, org_ids=None):
        """
        Assembles a data set representing the Top N users, by progress, for a given course.

        data = [
                {'id': 123, 'username': 'testuser1', 'title', 'Engineer', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'score': 80},
                {'id': 983, 'username': 'testuser2', 'title', 'Analyst', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'score': 70},
                {'id': 246, 'username': 'testuser3', 'title', 'Product Owner', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'score': 62},
                {'id': 357, 'username': 'testuser4', 'title', 'Director', 'profile_image_uploaded_at': '2014-01-15 06:27:54', 'completions': 58},
        ]

        """
        exclude_users = exclude_users or []
        queryset = cls.objects.select_related('user')\
            .filter(course_id__exact=course_key, user__is_active=True, user__courseenrollment__is_active=True,
                    user__courseenrollment__course_id__exact=course_key)

        if exclude_users:
            queryset = queryset.exclude(user__id__in=exclude_users)

        if org_ids:
            queryset = queryset.filter(user__organizations__in=org_ids)

        aggregates = queryset.aggregate(Sum('score'))
        course_avg = 0
        total_score = aggregates['score__sum'] if aggregates['score__sum'] else 0
        if total_score:
            total_user_count = CourseEnrollment.objects.users_enrolled_in(course_key).exclude(id__in=exclude_users).count()
            course_avg = int(round(total_score / float(total_user_count)))

        if count:
            queryset = queryset.values(
                'user__id',
                'user__username',
                'user__profile__title',
                'user__profile__profile_image_uploaded_at',
                'score',
                'modified')\
                .order_by('-score', 'modified')[:count]
        return course_avg, queryset


class StudentSocialEngagementScoreHistory(TimeStampedModel):
    """
    A running audit trail for the StudentProgress model.  Listens for
    post_save events and creates/stores copies of progress entries.
    """
    user = models.ForeignKey(User, db_index=True)
    course_id = CourseKeyField(db_index=True, max_length=255, blank=True)
    score = models.IntegerField()


@receiver(post_save, sender=StudentSocialEngagementScore)
def on_studentengagementscore_save(sender, instance, **kwargs):
    """
    When a studentengagementscore is saved, we want to also store the
    score value in the history table, so we have a complete history
    of the student's engagement score
    """
    invalid_user_data_cache('social', instance.course_id, instance.user.id)
    history_entry = StudentSocialEngagementScoreHistory(
        user=instance.user,
        course_id=instance.course_id,
        score=instance.score
    )
    history_entry.save()
