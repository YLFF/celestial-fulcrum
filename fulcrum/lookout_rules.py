"""Lookout sight ranges use grid distance, not traversable graph distance."""


def lookout_radii(difficulty: int = 15, split_unlocked: bool = True) -> tuple[int, int]:
    if type(difficulty) is not int or difficulty < 0:
        raise ValueError("difficulty must be a nonnegative integer")
    if type(split_unlocked) is not bool:
        raise ValueError("lookoutSplitUnlocked must be boolean")
    return (2, 3) if difficulty >= 3 and split_unlocked else (1, 2)
