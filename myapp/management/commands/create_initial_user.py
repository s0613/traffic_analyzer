
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Create initial user'

    def handle(self, *args, **kwargs):
        if not User.objects.filter(username='user@example.com').exists():
            User.objects.create_user(
                username='user@example.com',
                email='user@example.com',
                password='1234'
            )
            self.stdout.write(self.style.SUCCESS('Successfully created initial user'))
        else:
            self.stdout.write(self.style.WARNING('User already exists'))