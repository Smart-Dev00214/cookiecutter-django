# Generated by Django 3.2.18 on 2023-03-14 11:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0010_conditionaloffer_combinations'),
    ]

    operations = [
        migrations.AddField(
            model_name='rangeproductfileupload',
            name='included',
            field=models.BooleanField(default=True),
        ),
    ]