"""Trading environments used by the PPO pipeline.

This module contains the custom Gymnasium-compatible trading environment
used for continuous-position PPO training. It does not contain model
training, artifact saving, prediction, or live broker logic.
"""

from __future__ import annotations

import logging

import gymnasium as gym
import numpy as np
import pandas as pd
from gym_anytrading.envs import StocksEnv
from gymnasium.spaces import Box

from src.config import ENABLE_SENTIMENT


class ContinuousPositionEnv(StocksEnv):
    """Continuous-position trading environment with reward shaping.

    The action is a continuous target exposure in the range [-1, 1]:

    - -1.0 means fully short
    -  0.0 means flat
    -  1.0 means fully long

    The reward combines position return, relative alpha versus buy-and-hold,
    momentum carry, optional sentiment shaping, transaction cost, and slippage.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        frame_bound: tuple[int, int],
        window_size: int,
        cost_rate: float = 0.0002,
        slip_rate: float = 0.0003,
        k_alpha: float = 0.20,
        k_mom: float = 0.05,
        k_sent: float = 0.0,
        mom_source: str = "denoised",
        mom_lookback: int = 20,
        min_trade_delta: float = 0.01,
        cooldown: int = 5,
        reward_clip: float = 1.0,
    ) -> None:
        super().__init__(
            df=df.reset_index(drop=True),
            frame_bound=frame_bound,
            window_size=window_size,
        )

        if isinstance(self.observation_space, gym.spaces.Box):
            self.observation_space = Box(
                low=self.observation_space.low,
                high=self.observation_space.high,
                shape=self.observation_space.shape,
                dtype=self.observation_space.dtype,
            )

        self.action_space = Box(
            low=-1.0,
            high=1.0,
            shape=(1,),
            dtype=np.float32,
        )

        self.cost_rate = float(cost_rate)
        self.slip_rate = float(slip_rate)
        self.k_alpha = float(k_alpha)
        self.k_mom = float(k_mom)
        self.k_sent = float(k_sent)
        self.mom_source = str(mom_source)
        self.mom_lookback = int(mom_lookback)
        self.min_trade_delta = float(min_trade_delta)
        self.cooldown = int(cooldown)
        self.reward_clip = float(reward_clip)

        self.nav = 1.0
        self.pos = 0.0
        self._last_trade_step = -self.cooldown

    def reset(self, **kwargs):
        """Reset environment state."""
        output = super().reset(**kwargs)

        if isinstance(output, tuple):
            obs, info = output
        else:
            obs, info = output, {}

        self.nav = 1.0
        self.pos = 0.0
        self._last_trade_step = -self.cooldown

        info = info or {}
        info.update(
            {
                "nav": self.nav,
                "pos": self.pos,
            }
        )

        return obs, info

    def _step_parent_hold(self):
        """Advance the parent StocksEnv using a hold action.

        gym-anytrading versions can differ in whether they return the older
        4-value Gym API or the newer 5-value Gymnasium API. This wrapper
        normalizes the return signature.
        """
        step_result = super().step(2)

        if len(step_result) == 5:
            obs, _env_reward, terminated, truncated, info = step_result
        else:
            obs, _env_reward, done, info = step_result
            terminated = bool(done)
            truncated = False

        return obs, terminated, truncated, info

    def _ret_t(self) -> float:
        """Return close-to-close percentage return for the current tick."""
        current_price = float(self.df.loc[self._current_tick, "Close"])
        previous_price = float(self.df.loc[max(self._current_tick - 1, 0), "Close"])

        if previous_price <= 0:
            return 0.0

        return (current_price - previous_price) / previous_price

    def _mom_signal(self) -> float:
        """Compute a bounded momentum signal for reward shaping."""
        if self.mom_source == "macd" and "MACD_Line" in self.df.columns:
            recent = self.df["MACD_Line"].iloc[
                max(self._current_tick - 200, 0) : self._current_tick + 1
            ]

            recent_std = float(recent.std()) if len(recent) else 0.0
            current_macd = float(self.df.loc[self._current_tick, "MACD_Line"])

            return float(np.tanh(current_macd / (1e-6 + recent_std)))

        if (
            "Denoised_Close" in self.df.columns
            and self._current_tick - self.mom_lookback >= 0
        ):
            now = float(self.df.loc[self._current_tick, "Denoised_Close"])
            then = float(
                self.df.loc[self._current_tick - self.mom_lookback, "Denoised_Close"]
            )
            base = float(self.df.loc[max(self._current_tick - 1, 0), "Close"])

            slope = (now - then) / max(self.mom_lookback, 1)

            return float(np.tanh(10.0 * (slope / max(abs(base), 1e-6))))

        return 0.0

    def step(self, action):
        """Advance one environment step using a continuous target position."""
        try:
            action_value = float(np.array(action).squeeze())
            target_pos = float(np.clip(action_value, -1.0, 1.0))

            ret_t = self._ret_t()
            base_ret = self.pos * ret_t

            can_trade = (self._current_tick - self._last_trade_step) >= self.cooldown
            trade_large_enough = abs(target_pos - self.pos) >= self.min_trade_delta
            changed = trade_large_enough and can_trade

            delta_pos = target_pos - self.pos if changed else 0.0
            trade_cost = (self.cost_rate + self.slip_rate) * abs(delta_pos)

            relative_alpha = base_ret - ret_t
            momentum_term = self.pos * self._mom_signal()

            sentiment_term = 0.0
            if ENABLE_SENTIMENT and "SentimentScore" in self.df.columns:
                sentiment_term = self.k_sent * float(
                    self.df.loc[self._current_tick, "SentimentScore"]
                )

            shaped_reward = (
                base_ret
                + self.k_alpha * relative_alpha
                + self.k_mom * momentum_term
                + sentiment_term
                - trade_cost
            )

            reward = float(
                np.clip(shaped_reward, -self.reward_clip, self.reward_clip)
            )

            self.nav *= 1.0 + base_ret - trade_cost

            if changed:
                self.pos = target_pos
                self._last_trade_step = self._current_tick

            obs, terminated, truncated, info = self._step_parent_hold()

            info = info or {}
            info.update(
                {
                    "ret_t": ret_t,
                    "nav": self.nav,
                    "pos": self.pos,
                    "trade_cost": trade_cost,
                    "base_ret": base_ret,
                    "rel_alpha": relative_alpha,
                    "mom": self._mom_signal(),
                }
            )

            return obs, reward, terminated, truncated, info

        except Exception as exc:
            logging.error("Environment step failed: %s", exc)

            try:
                obs, _ = self.reset()
            except Exception:
                obs = None

            return obs, 0.0, True, False, {}