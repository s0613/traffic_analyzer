import os
import csv
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from django.utils.timezone import make_aware
from myapp.models import Site, ResponseTimeLog


class Command(BaseCommand):
    help = "Import CSV logs into DB (initial)."

    def add_arguments(self, parser):
        parser.add_argument('--folder', type=str, required=True, help="Path to the folder containing CSV files.")

    def handle(self, *args, **options):
        folder = options['folder']
        if not os.path.isdir(folder):
            self.stdout.write(self.style.ERROR(f"Folder not found: {folder}"))
            return

        csv_files = [f for f in os.listdir(folder) if f.endswith('.csv')]
        total_imported = 0

        for fname in csv_files:
            file_path = os.path.join(folder, fname)
            site_domain = fname[:-4]  # Remove ".csv" from filename
            site_obj, created = Site.objects.get_or_create(domain=site_domain, defaults={"active": True})

            bulk_objs = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)  # Use DictReader for header support
                for row in reader:
                    try:
                        ts_str = row.get("timestamp", "").strip()  # Extract timestamp
                        resp_str = row.get("response_time", "").strip()  # Extract response_time

                        if not ts_str or not resp_str:
                            continue  # Skip if required fields are missing

                        dt = parse_datetime(ts_str)  # Parse timestamp to datetime
                        if dt is not None:
                            dt = make_aware(dt)  # Convert naive datetime to timezone-aware

                        response_time = float(resp_str)  # Convert response_time to float
                        bulk_objs.append(ResponseTimeLog(
                            site=site_obj,
                            timestamp=dt,
                            response_time=response_time
                        ))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Error parsing row: {row} - {e}"))

            ResponseTimeLog.objects.bulk_create(bulk_objs)
            imported_count = len(bulk_objs)
            total_imported += imported_count
            self.stdout.write(self.style.SUCCESS(f"Imported {imported_count} logs for site: {site_domain}"))

        self.stdout.write(self.style.SUCCESS(f"Total imported logs: {total_imported}"))
