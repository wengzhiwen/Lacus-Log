# pylint: disable=import-error,no-member
import pytest
from mongoengine import connect, disconnect

from models.battle_area import Availability, BattleArea


@pytest.mark.unit
class TestBattleAreaModel:
    """战斗区域模型单元测试"""

    def test_creation_defaults(self):
        area = BattleArea(x_coord="无锡50", y_coord="房间A", z_coord="11")
        assert area.availability == Availability.ENABLED
        assert area.created_at is not None
        assert area.updated_at is not None

    def test_validation_required_fields(self):
        area = BattleArea()
        with pytest.raises(Exception):
            area.clean()

    def test_strip_inputs(self):
        area = BattleArea(x_coord="  X  ", y_coord="  Y ", z_coord=" Z  ")
        area.clean()
        assert area.x_coord == "X"
        assert area.y_coord == "Y"
        assert area.z_coord == "Z"


@pytest.mark.integration
@pytest.mark.requires_db
class TestBattleAreaIntegration:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        yield

    def test_unique_constraint(self):
        a1 = BattleArea(x_coord="X", y_coord="Y", z_coord="1")
        a1.save()
        a2 = BattleArea(x_coord="X", y_coord="Y", z_coord="1")
        with pytest.raises(Exception):
            a2.save()
