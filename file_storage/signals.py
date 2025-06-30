import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from file_storage.models import UserFile

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=UserFile)
def delete_file_from_s3(sender, instance, **kwargs):
    """Удаляет файл из Minio после удаления объекта UserFile из БД."""
    instance.file.delete(save=False)
    logger.info(f"User: '{instance.user}' deleted file from S3/minio successful")
