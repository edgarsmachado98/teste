from vigia_detector.clips import ClipRecorder


def frames(rec, start, end, step=0.5):
    done = []
    t = start
    while t <= end + 1e-9:
        done += rec.add(t, f"f{t}".encode())
        t += step
    return done


def test_clip_has_before_and_after():
    rec = ClipRecorder(before=2, after=2)
    assert frames(rec, 0, 10) == []
    clip_id = rec.start(10)  # quadro de t=10 já está no buffer
    done = frames(rec, 10.5, 12)
    assert len(done) == 1
    cid, clip, duration = done[0]
    assert cid == clip_id
    assert clip[0] == b"f8.0" and clip[-1] == b"f12.0"
    assert len(clip) == 9 and duration == 4.0


def test_overlapping_clips_and_cap():
    rec = ClipRecorder(before=1, after=3, max_frames=5)
    frames(rec, 0, 2)
    a = rec.start(2)
    frames(rec, 2.5, 3)
    b = rec.start(3)
    done = frames(rec, 3.5, 6)
    assert [d[0] for d in done] == [a, b]
    assert all(len(d[1]) <= 5 for d in done)


def test_flush_on_disconnect():
    rec = ClipRecorder(before=1, after=10)
    frames(rec, 0, 1)
    rec.start(1)
    flushed = rec.flush()
    assert len(flushed) == 1 and flushed[0][1]
    assert rec.flush() == []
