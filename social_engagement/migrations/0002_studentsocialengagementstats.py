# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone
import model_utils.fields


def create_stats(apps, schema_editor):
    StudentSocialEngagementScore = apps.get_model('social_engagement', 'StudentSocialEngagementScore')
    StudentSocialEngagementStats = apps.get_model('social_engagement', 'StudentSocialEngagementStats')

    for score in StudentSocialEngagementScore.objects.all():
        score.stats = StudentSocialEngagementStats.objects.create(score=score)


class Migration(migrations.Migration):

    dependencies = [
        ('social_engagement', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentSocialEngagementStats',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, verbose_name='created', editable=False)),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, verbose_name='modified', editable=False)),
                ('score', models.OneToOneField(related_name='stats', primary_key=True, serialize=False, to='social_engagement.StudentSocialEngagementScore')),
                ('num_threads', models.IntegerField(default=0, db_index=True)),
                ('num_thread_followers', models.IntegerField(default=0, db_index=True)),
                ('num_replies', models.IntegerField(default=0, db_index=True)),
                ('num_flagged', models.IntegerField(default=0, db_index=True)),
                ('num_comments', models.IntegerField(default=0, db_index=True)),
                ('num_threads_read', models.IntegerField(default=0, db_index=True)),
                ('num_downvotes', models.IntegerField(default=0, db_index=True)),
                ('num_upvotes', models.IntegerField(default=0, db_index=True)),
                ('num_comments_generated', models.IntegerField(default=0, db_index=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.RunPython(create_stats)
    ]
