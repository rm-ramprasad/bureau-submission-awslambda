"""Reference data seed: the database is the master; the seed only adds missing rows."""

from sqlalchemy import delete, select, update

from submissions.canonical.schema import ref_code_translation
from submissions.reference import active_translations, seed

T = ref_code_translation.c


def test_seed_adds_missing_rows_and_keeps_edits(engine):
    with engine.begin() as conn:                         # conftest seeded; edit one row, remove another
        conn.execute(update(ref_code_translation).where(T.submission_type == "CONSUMER", T.code_list == "gender",
                                                        T.code == "MALE").values(output_code="M"))
        conn.execute(delete(ref_code_translation).where(T.submission_type == "CONSUMER", T.code_list == "gender",
                                                        T.code == "FEMALE"))
    counts = seed(engine)
    assert counts["ref_code_translation"] == 1 and counts["ref_code"] == 0
    with engine.connect() as conn:
        gender = active_translations(conn, "CONSUMER")["gender"]
    assert gender["MALE"] == "M" and gender["FEMALE"] == "1"          # edit kept, missing row back


def test_active_translations_skip_inactive(engine):
    with engine.connect() as conn:
        ids = active_translations(conn, "CONSUMER")["id_type"]
        inactive = conn.execute(select(T.code).where(T.code_list == "id_type", T.is_active.is_(False))).scalars().all()
    assert ids["PAN"] == "01" and set(inactive) == {"ADDITIONAL_ID_1", "ADDITIONAL_ID_2"}
    assert not set(inactive) & set(ids)
