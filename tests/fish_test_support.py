from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from igess.fish_data import FishDataSnapshot


@dataclass(frozen=True)
class _BigNumber:
    sign: int
    digits: str
    scale: int


def _big(value: int) -> _BigNumber:
    return _BigNumber(1, str(value), 0)


def _snapshot(
    tmp_path: Path,
    *,
    initial_torpedo_id: int = 1,
    trash_duration: int = 300,
) -> FishDataSnapshot:
    tables = {
        "tbfishrandompool": (
            SimpleNamespace(
                id=1,
                rarityId=1,
                strengthUpperBound=_big(50),
                startLuck=1,
                endLuck=3,
            ),
            SimpleNamespace(
                id=2,
                rarityId=2,
                strengthUpperBound=_big(2000),
                startLuck=5,
                endLuck=8,
            ),
        ),
        "tbtrashrandompool": (
            SimpleNamespace(
                id=1,
                rarityId=1,
                powerUpperBound=_big(50),
                name="池1",
                startLuck=1,
                endLuck=3,
            ),
            SimpleNamespace(
                id=2,
                rarityId=2,
                powerUpperBound=_big(2000),
                name="池2",
                startLuck=5,
                endLuck=8,
            ),
        ),
        "tbbonusfirstlayer": (
            SimpleNamespace(
                id=1,
                resultType=0,
                name="无 Bonus",
                rollPowerRequirement=1,
                continueChain=False,
                luckMultiplier=1,
            ),
            SimpleNamespace(
                id=2,
                resultType=1,
                name="进入变异",
                rollPowerRequirement=3.787878787878788,
                continueChain=True,
                luckMultiplier=1,
            ),
            SimpleNamespace(
                id=3,
                resultType=2,
                name="Luck ×2",
                rollPowerRequirement=10,
                continueChain=True,
                luckMultiplier=2,
            ),
        ),
        "tbmutation": (
            SimpleNamespace(
                id=7,
                name="正常",
                mutationWeight=0,
                incomeMultiplier=1,
            ),
            SimpleNamespace(
                id=2,
                name="金色",
                mutationWeight=100000,
                incomeMultiplier=1.5,
            ),
        ),
        "tbfish": (
            SimpleNamespace(
                id=1,
                baseMoneyPerSecond=_big(10),
                name="鱼1",
                rarityId=1,
                Denominator=_big(1),
                weight=1250,
            ),
            SimpleNamespace(
                id=2,
                baseMoneyPerSecond=_big(8),
                name="鱼2",
                rarityId=2,
                Denominator=_big(10),
                weight=800,
            ),
        ),
        "tbtrash": (
            SimpleNamespace(
                id=1,
                name="废料1",
                baseDecomposeSeconds=trash_duration,
                baseMaterialPerSecond=_big(2),
                rarityId=1,
                Denominator=_big(1),
            ),
            SimpleNamespace(
                id=2,
                name="废料2",
                baseDecomposeSeconds=trash_duration,
                baseMaterialPerSecond=_big(4),
                rarityId=2,
                Denominator=_big(10),
            ),
        ),
        "tbtrashmanrealm": (
            SimpleNamespace(
                id=1,
                name="初境",
                decomposeSpeedMultiplier=1,
                cultivationSecondsToNextRealm=0,
            ),
            SimpleNamespace(
                id=2,
                name="二境",
                decomposeSpeedMultiplier=1.25,
                cultivationSecondsToNextRealm=1,
            ),
            SimpleNamespace(
                id=3,
                name="三境",
                decomposeSpeedMultiplier=2,
                cultivationSecondsToNextRealm=2,
            ),
        ),
        "tbtrashmanrebirth": (
            SimpleNamespace(
                id=0,
                realmRequirement=0,
                trashToTreasureOutputMultiplier=2,
            ),
            SimpleNamespace(
                id=1,
                realmRequirement=4,
                trashToTreasureOutputMultiplier=3,
            ),
        ),
        "tbtorpedo": (
            SimpleNamespace(
                id=initial_torpedo_id,
                name="初始鱼雷",
                rarityId=1,
                power=_big(50),
            ),
        ),
        "tbbarbell": (
            SimpleNamespace(
                id=1,
                name="杠铃1",
                strengthPerExercise=2,
                price=_big(20),
                rarityId=1,
                timeCost=1,
            ),
            SimpleNamespace(
                id=2,
                name="杠铃2",
                strengthPerExercise=5,
                price=_big(75),
                rarityId=2,
                timeCost=1,
            ),
        ),
        "tbstrengthrebirth": (
            SimpleNamespace(
                id=1,
                strengthRequirement=_big(1000),
                fishHallOutputMultiplier=2,
            ),
            SimpleNamespace(
                id=2,
                strengthRequirement=_big(10000),
                fishHallOutputMultiplier=3,
            ),
        ),
        "tbfishhallupgrade": (
            SimpleNamespace(
                id=11,
                upgradePrice=_big(100),
                slotQty=2,
            ),
            SimpleNamespace(
                id=12,
                upgradePrice=_big(0),
                slotQty=3,
            ),
        ),
    }
    return FishDataSnapshot(
        root=tmp_path,
        tables=tables,
        files=(),
        loader_files=(),
        production_data=False,
    )
