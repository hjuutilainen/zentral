# -*- coding: utf-8 -*-
# Generated by Django 1.10.2 on 2016-11-04 13:43
from __future__ import unicode_literals

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('probes', '0004_auto_20161103_1728'),
    ]

    operations = [
        migrations.AddField(
            model_name='probesource',
            name='apps',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=255), blank=True, default=[], editable=False, size=None),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='probesource',
            name='event_types',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=255), blank=True, default=[], editable=False, size=None),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='probesource',
            name='model',
            field=models.CharField(blank=True, editable=False, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='probesource',
            name='body',
            field=models.TextField(editable=False),
        ),
        migrations.AlterField(
            model_name='probesource',
            name='slug',
            field=models.SlugField(editable=False, max_length=255, unique=True),
        ),
    ]
