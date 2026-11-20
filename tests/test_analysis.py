import pytest

from carteira import analysis


def test_sma():
    assert analysis.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_ema_inicia_com_sma():
    e = analysis.ema([1, 2, 3, 4, 5], 3)
    assert e[:2] == [None, None]
    assert e[2] == pytest.approx(2)
    assert e[3] == pytest.approx(3)


def test_rsi_extremos():
    assert analysis.rsi(list(range(1, 30)))[-1] == 100
    assert analysis.rsi(list(range(30, 1, -1)))[-1] == 0


def test_drawdown_e_retorno():
    assert analysis.max_drawdown([100, 120, 60, 130]) == pytest.approx(-0.5)
    assert analysis.retorno_periodo([100, 110, 121], 2) == pytest.approx(0.21)
    assert analysis.retorno_periodo([100], 5) is None


def test_correlacao():
    assert analysis.correlacao([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1)
    assert analysis.correlacao([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1)


def test_analisar_completo():
    fech = [100 + i + (i % 7) for i in range(300)]
    datas = [f"d{i}" for i in range(300)]
    r = analysis.analisar(datas, fech)
    assert len(r["mm200"]) == 300 and r["mm200"][-1] is not None
    assert r["macd_sinal"][-1] is not None
    assert any("200 dias" in s["texto"] for s in r["sinais"])
