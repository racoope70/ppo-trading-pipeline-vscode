from src.cli_utils import parse_ticker_args


def test_parse_ticker_args_space_separated():
    assert parse_ticker_args(["AAPL", "pfe", "UNH"]) == ["AAPL", "PFE", "UNH"]


def test_parse_ticker_args_comma_separated():
    assert parse_ticker_args(["AAPL,PFE,UNH,XOM"]) == ["AAPL", "PFE", "UNH", "XOM"]


def test_parse_ticker_args_mixed_and_deduped():
    assert parse_ticker_args(["AAPL,PFE", "UNH", "aapl", " XOM "]) == [
        "AAPL",
        "PFE",
        "UNH",
        "XOM",
    ]


def test_parse_ticker_args_none_or_empty():
    assert parse_ticker_args(None) is None
    assert parse_ticker_args([]) is None
    assert parse_ticker_args(["", "   "]) is None