from storages.backends.s3boto3 import S3Boto3Storage


class CustomS3Boto3Storage(S3Boto3Storage):
    def get_valid_name(self, name):
        return name
