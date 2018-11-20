# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('social_engagement', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_comments',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_comments_generated',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_downvotes',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_flagged',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_replies',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_thread_followers',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_threads',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_threads_read',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='studentsocialengagementscore',
            name='num_upvotes',
            field=models.IntegerField(default=0),
        ),
    ]
