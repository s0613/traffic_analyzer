# myapp/apps.py
from django.apps import AppConfig
from django.db.utils import OperationalError

class MyAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'

    def ready(self):
        # Import your own models or signals here (AFTER apps are loaded)
        import myapp.signals
        from myapp.models import Site
        from myapp.ml.training import train_site_model

        # 2) Train all sites on startup
        try:
            sites = Site.objects.all()
            for site in sites:
                print(f"Training model for site: {site.domain}")
                train_site_model(site.id)
        except OperationalError:
            print("[INFO] Database not ready. Skipping model training during initialization.")

