from test_loveletter.utils import collect_card_classes


def test_cards_have_unique_nonnegative_value():
    classes = collect_card_classes()
    values = {cls.value for cls in classes}
    assert len(values) == len(classes)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)
