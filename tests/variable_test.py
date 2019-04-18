
import pytest

from delphin import variable

def test_split():
    assert variable.split('x1') == ('x', '1')
    assert variable.split('event10') == ('event', '10')
    assert variable.split('ref-ind2') == ('ref-ind', '2')
    with pytest.raises(ValueError):
        variable.split('x')
    with pytest.raises(ValueError):
        variable.split('1')
    with pytest.raises(ValueError):
        variable.split('1x')


def test_type():
    assert variable.type('x1') == 'x'
    assert variable.type('event10') == 'event'
    assert variable.type('ref-ind2') == 'ref-ind'
    with pytest.raises(ValueError):
        variable.type('x')
    # and sort alias
    assert variable.sort('x1') == 'x'


def test_id():
    assert variable.id('x1') == 1
    assert variable.id('event10') == 10
    assert variable.id('ref-ind2') == 2
    with pytest.raises(ValueError):
        variable.id('1')


def test_is_valid():
    assert variable.is_valid('h3') == True
    assert variable.is_valid('ref-ind12') == True
    assert variable.is_valid('x') == False
    assert variable.is_valid('1') == False
    assert variable.is_valid('x 1') == False


class TestVariableFactory():
    def test_init(self):
        vf = variable.VariableFactory()
        assert vf.vid == 1
        assert len(vf.store) == 0
        vf = variable.VariableFactory(starting_vid=5)
        assert vf.vid == 5
        assert len(vf.store) == 0

    def test_new(self):
        vf = variable.VariableFactory()
        v, vps = vf.new('x')
        assert v == 'x1'
        assert vf.vid == 2
        assert len(vf.store['x1']) == len(vps) == 0
        v, vps = vf.new('e', [('PROP', 'VAL')])
        assert v == 'e2'
        assert vf.vid == 3
        assert len(vf.store['e2']) == len(vps) == 1

