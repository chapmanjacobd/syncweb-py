import pytest

from syncweb import str_utils
from syncweb.str_utils import FolderRef, extract_device_id


@pytest.mark.parametrize(
    "value,expected",
    [
        # Canonical valid ID
        (
            "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD",
            "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD",
        ),
        # Lowercase → normalized uppercase
        (
            "mfzwi3d-bonsgyc-yltmrwg-c43enr5-qxgzdmm-fzwi3dp-bonsgyy-ltmrwad",
            "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD",
        ),
        # Periods accepted (normalize to '-')
        (
            "MFZWI3D.BONSGYC.YLTMRWG.C43ENR5.QXGZDMM.FZWI3DP.BONSGYY.LTMRWAD",
            "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD",
        ),
        # No dashes (auto-grouped into 7-char chunks)
        (
            "MFZWI3DBONSGYCYLTMRWGC43ENR5QXGZDMMFZWI3DPBONSGYYLTMRWAD",
            "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD",
        ),
    ],
)
def test_extract_device_id_valid(value, expected):
    assert extract_device_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        # Too short
        "MFZWI3D",
        "MFZWI3DBONSGYC",
        # Too long
        "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD-EXTRA",
        # Invalid chars
        "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONS@YY-LTMRWAD",
        # Empty
        "",
        # Bad format (extra periods/dashes)
        "MFZWI3D--BONSGYC-YLTMRWG",
    ],
)
def test_extract_device_id_invalid(value):
    with pytest.raises(ValueError):
        str_utils.extract_device_id(value)


TEST_DEVICE_ID = "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYY-LTMRWAD"


@pytest.mark.parametrize(
    "value,expected",
    [
        # Simple folder only
        ("grape-juice", FolderRef("grape-juice", None, None)),
        # Folder + device ID
        ("syncweb://grape-juice#" + TEST_DEVICE_ID, FolderRef("grape-juice", None, TEST_DEVICE_ID)),
        # Folder + subpath + device ID
        ("syncweb://grape-juice/sub/f.txt#" + TEST_DEVICE_ID, FolderRef("grape-juice", "sub/f.txt", TEST_DEVICE_ID)),
        # Unicode folder
        ("syncweb://データ#" + TEST_DEVICE_ID, FolderRef("データ", None, TEST_DEVICE_ID)),
        # Unicode subpath
        ("syncweb://データ//サブ#" + TEST_DEVICE_ID, FolderRef("データ", "サブ", TEST_DEVICE_ID)),
        # Percent-decoded
        ("syncweb://grape%20juice#" + TEST_DEVICE_ID, FolderRef("grape%20juice", None, TEST_DEVICE_ID)),
        # Folder ID with '#' inside
        ("syncweb://foo#bar#" + TEST_DEVICE_ID, FolderRef("foo#bar", None, TEST_DEVICE_ID)),
        # One more for good measure
        (
            "syncweb://%E3%83%87%E3%83%BC%E3%82%BF#/test/%E3%83%87%E3%83#%BC%E3%82%BF#" + TEST_DEVICE_ID,
            FolderRef("%E3%83%87%E3%83%BC%E3%82%BF#", "test/%E3%83%87%E3%83#%BC%E3%82%BF", TEST_DEVICE_ID),
        ),
    ],
)
def test_parse_syncweb_path_no_decode(value, expected):
    result = str_utils.parse_syncweb_path(value, decode=False)
    assert result == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        # Simple folder only
        ("grape-juice", FolderRef("grape-juice", None, None)),
        # Device ID only
        (TEST_DEVICE_ID, FolderRef(TEST_DEVICE_ID, None, TEST_DEVICE_ID)),
        # Folder + device ID
        ("syncweb://grape-juice#" + TEST_DEVICE_ID, FolderRef("grape-juice", None, TEST_DEVICE_ID)),
        # Folder + subpath + device ID
        ("syncweb://grape-juice/sub/f.txt#" + TEST_DEVICE_ID, FolderRef("grape-juice", "sub/f.txt", TEST_DEVICE_ID)),
        # Unicode folder
        ("syncweb://データ#" + TEST_DEVICE_ID, FolderRef("データ", None, TEST_DEVICE_ID)),
        # Unicode subpath
        ("syncweb://データ//サブ#" + TEST_DEVICE_ID, FolderRef("データ", "サブ", TEST_DEVICE_ID)),
        # Percent-decoded
        ("syncweb://grape%20juice#" + TEST_DEVICE_ID, FolderRef("grape juice", None, TEST_DEVICE_ID)),
        # Folder ID with '#' inside
        ("syncweb://foo#bar#" + TEST_DEVICE_ID, FolderRef("foo#bar", None, TEST_DEVICE_ID)),
        # traversal in subpath
        ("syncweb://folder/../../etc", FolderRef("folder", "etc", None)),
        # absolute file
        ("syncweb:///abs/path", FolderRef("abs", "path", None)),
        # absolute folder
        ("syncweb:///abs/path/", FolderRef("abs", "path/", None)),
        # One more for good measure
        (
            "syncweb://%E3%83%87%E3%83%BC%E3%82%BF#/test#1/%E3%83%87%E3%83%BC%E3%82%BF##" + TEST_DEVICE_ID,
            FolderRef("データ#", "test#1/データ#", TEST_DEVICE_ID),
        ),
    ],
)
def test_parse_syncweb_path_valid(value, expected):
    result = str_utils.parse_syncweb_path(value)
    assert result == expected


@pytest.mark.parametrize(
    "value",
    [
        "syncweb://",  # missing folder
        "syncweb://../evil",  # traversal in folder
    ],
)
def test_parse_syncweb_path_invalid(value):
    with pytest.raises(ValueError):
        str_utils.parse_syncweb_path(value)


def test_plain_folder_with_unicode():
    ref = str_utils.parse_syncweb_path("🍇project")
    assert ref.folder_id == "🍇project"
    assert ref.subpath is None
    assert ref.device_id is None
