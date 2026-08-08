from storages.backends.gcloud import GoogleCloudStorage
from django.core.files.storage import FileSystemStorage
from google.auth.exceptions import DefaultCredentialsError

class CustomGoogleCloudStorage(GoogleCloudStorage):
    def url(self, name):
        if not name:
            return ""
        bucket = getattr(self, 'bucket_name', 'quicknest-media-2026') or 'quicknest-media-2026'
        clean_name = str(name).lstrip('/')
        return f"https://storage.googleapis.com/{bucket}/{clean_name}"

    def _save(self, name, content):
        try:
            return super()._save(name, content)
        except Exception:
            # If GCS credentials are missing on local dev, fallback to local FileSystemStorage
            fs = FileSystemStorage()
            return fs._save(name, content)
