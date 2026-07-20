"""Tests for run.py helpers: MongoDB URI masking and version resolution."""

from run import _get_version, mask_mongo_uri


class TestMaskMongoUri:
    def test_masks_password_keeps_username(self):
        assert (
            mask_mongo_uri("mongodb+srv://alice:s3cret@cluster.mongodb.net")
            == "mongodb+srv://alice:****@cluster.mongodb.net"
        )

    def test_masks_password_in_plain_uri(self):
        assert (
            mask_mongo_uri("mongodb://bob:passw0rd@localhost:27017")
            == "mongodb://bob:****@localhost:27017"
        )

    def test_uri_without_credentials_unchanged(self):
        assert mask_mongo_uri("mongodb://localhost:27017") == "mongodb://localhost:27017"

    def test_none_returns_not_configured(self):
        assert mask_mongo_uri(None) == "Not configured"

    def test_empty_string_returns_not_configured(self):
        assert mask_mongo_uri("") == "Not configured"


class TestGetVersion:
    def test_returns_a_nonempty_string(self):
        v = _get_version()
        assert isinstance(v, str)
        assert v
