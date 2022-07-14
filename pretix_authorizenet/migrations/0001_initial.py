# Generated by Django 3.2.12 on 2022-07-14 09:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('pretixbase', '0218_checkinlist_addon_match'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReferencedAuthorizeNetObject',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('reference', models.CharField(db_index=True, max_length=190, unique=True)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pretixbase.order')),
                ('payment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pretixbase.orderpayment')),
            ],
        ),
    ]
