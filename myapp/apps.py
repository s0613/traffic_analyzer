# myapp/apps.py
from django.apps import AppConfig
from django.db.utils import OperationalError
from django.core.exceptions import ObjectDoesNotExist

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
                try:
                    print(f"[INFO] Training model for site: {site.domain}")
                    train_site_model(site.domain)  # site.domain을 인자로 전달
                except ObjectDoesNotExist:
                    print(f"[WARNING] Site not found: {site.domain}. Skipping training.")
                except Exception as e:
                    print(f"[ERROR] Failed to train model for site {site.domain}: {e}")
        except OperationalError:
            print("[INFO] Database not ready. Skipping model training during initialization.")