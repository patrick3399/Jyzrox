"""Regression tests for the Tier-1 pHash pair scan (worker/dedup_helpers._scan_candidates).

Memory-leak root cause: the original Tier-1 loop iterated ``for b in blobs[i + 1:]``,
allocating a fresh copy of the (potentially million-row) blob list on every outer
iteration — O(n^2) allocation churn that fragmented the heap and drove the worker
RSS toward the 2 GB cap (host memory exhaustion before the cap existed). The scan
must walk by index without ever slicing ``blobs`` while producing identical pairs.
"""

from worker.dedup_helpers import _scan_candidates


class _Blob:
    def __init__(self, sha, phash_int, q0=0, q1=0):
        self.sha256 = sha
        self.phash_int = phash_int
        self.phash_q0 = q0
        self.phash_q1 = q1


def test_bk_tree_matches_brute_force_hamming_radius():
    from worker.dedup_helpers import PhashBKTree, _hamming_distance

    blobs = [_Blob(f"sha-{i}", (i * 0x9E3779B97F4A7C15) & ((1 << 64) - 1), 0, 0) for i in range(200)]
    index = PhashBKTree(blobs)

    for query in blobs[::17]:
        for threshold in (0, 5, 10):
            expected = {
                blob.sha256 for blob in blobs if _hamming_distance(query.phash_int, blob.phash_int) <= threshold
            }
            actual = {blob.sha256 for blob, _distance in index.query(query.phash_int, threshold)}
            assert actual == expected


def test_bk_tree_groups_equal_hashes_without_losing_items():
    from worker.dedup_helpers import PhashBKTree

    blobs = [_Blob(f"same-{i}", 1234, 0, 0) for i in range(20)]
    matches = list(PhashBKTree(blobs).query(1234, 0))

    assert {blob.sha256 for blob, distance in matches if distance == 0} == {blob.sha256 for blob in blobs}


class _SliceForbiddenList(list):
    """A list that raises if sliced — proves the scan never copies the blob list."""

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise AssertionError("blobs sliced — reintroduces per-iteration O(n) copy (memory regression)")
        return super().__getitem__(index)


def test_identical_phash_yields_pair_with_zero_distance():
    blobs = [_Blob("a", 0xDEADBEEF), _Blob("b", 0xDEADBEEF)]
    pairs = list(_scan_candidates(blobs, 0, threshold=10))
    assert len(pairs) == 1
    b, dist = pairs[0]
    assert b.sha256 == "b"
    assert dist == 0


def test_distant_phash_yields_no_pair():
    blobs = [_Blob("a", 0x0, q0=0, q1=0), _Blob("b", 0xFFFFFFFFFFFFFFFF, q0=0xFFFF, q1=0xFFFF)]
    assert list(_scan_candidates(blobs, 0, threshold=10)) == []


def test_pigeonhole_prefilter_skips_when_q01_exceeds_threshold():
    # q0 differs by 16 bits → q01_dist > threshold → skipped before full compare
    blobs = [_Blob("a", 0x0, q0=0x0, q1=0x0), _Blob("b", 0x0, q0=0xFFFF, q1=0x0)]
    assert list(_scan_candidates(blobs, 0, threshold=10)) == []


def test_full_distance_above_threshold_skipped_after_prefilter_passes():
    # q01_dist = 0 (passes prefilter) but full 64-bit distance = 64 > threshold
    blobs = [_Blob("a", 0x0, q0=0, q1=0), _Blob("b", 0xFFFFFFFFFFFFFFFF, q0=0, q1=0)]
    assert list(_scan_candidates(blobs, 0, threshold=10)) == []


def test_scan_does_not_slice_the_blob_list():
    blobs = _SliceForbiddenList([_Blob(str(i), 0xABCD) for i in range(20)])
    pairs = list(_scan_candidates(blobs, 0, threshold=10))
    assert len(pairs) == 19  # blob 0 vs 1..19, all identical


def test_only_scans_indices_after_i():
    blobs = [_Blob("a", 0xABCD), _Blob("b", 0xABCD), _Blob("c", 0xABCD)]
    pairs = list(_scan_candidates(blobs, 1, threshold=10))
    assert [b.sha256 for b, _ in pairs] == ["c"]
