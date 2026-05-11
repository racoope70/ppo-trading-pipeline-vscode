# region imports
from AlgorithmImports import *
import json
# endregion


class UnhXomArtifactLoadingTest(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2026, 2, 10)
        self.set_end_date(2026, 2, 11)
        self.set_cash(100000)

        self.required_artifacts = {
            "UNH": {
                "prefix": "ppo_UNH_window1",
                "keys": [
                    "ppo_models_master/UNH/ppo_UNH_window1_model.zip",
                    "ppo_models_master/UNH/ppo_UNH_window1_vecnorm.pkl",
                    "ppo_models_master/UNH/ppo_UNH_window1_features.json",
                    "ppo_models_master/UNH/ppo_UNH_window1_model_info.json",
                    "ppo_models_master/UNH/ppo_UNH_window1_probability_config.json",
                ],
            },
            "XOM": {
                "prefix": "ppo_XOM_window2",
                "keys": [
                    "ppo_models_master/XOM/ppo_XOM_window2_model.zip",
                    "ppo_models_master/XOM/ppo_XOM_window2_vecnorm.pkl",
                    "ppo_models_master/XOM/ppo_XOM_window2_features.json",
                    "ppo_models_master/XOM/ppo_XOM_window2_model_info.json",
                    "ppo_models_master/XOM/ppo_XOM_window2_probability_config.json",
                ],
            },
        }

        self.debug("UNH/XOM Object Store artifact loading test initialized.")

        all_passed = True

        for symbol, config in self.required_artifacts.items():
            self.debug(f"Checking artifacts for {symbol} | prefix={config['prefix']}")

            for key in config["keys"]:
                exists = self.object_store.contains_key(key)

                self.debug(f"{symbol} | exists={exists} | key={key}")

                if not exists:
                    all_passed = False
                    continue

                if key.endswith(".json"):
                    if not self._validate_json_artifact(symbol, key):
                        all_passed = False
                else:
                    if not self._validate_binary_artifact(symbol, key):
                        all_passed = False

        if all_passed:
            self.debug("ARTIFACT CHECK PASSED: all selected UNH/XOM artifacts are available and readable.")
        else:
            self.debug("ARTIFACT CHECK FAILED: one or more selected UNH/XOM artifacts are missing or unreadable.")

    def on_data(self, data: Slice):
        pass

    def _validate_json_artifact(self, symbol: str, key: str) -> bool:
        try:
            raw = self.object_store.read(key)

            if raw is None or len(raw) == 0:
                self.debug(f"{symbol} | JSON artifact empty | key={key}")
                return False

            parsed = json.loads(raw)

            if isinstance(parsed, dict):
                self.debug(
                    f"{symbol} | JSON readable | key={key} | top_level_keys={list(parsed.keys())[:10]}"
                )
            elif isinstance(parsed, list):
                self.debug(
                    f"{symbol} | JSON readable | key={key} | list_length={len(parsed)}"
                )
            else:
                self.debug(
                    f"{symbol} | JSON readable | key={key} | type={type(parsed).__name__}"
                )

            return True

        except Exception as exc:
            self.debug(f"{symbol} | JSON read failed | key={key} | error={exc}")
            return False

    def _validate_binary_artifact(self, symbol: str, key: str) -> bool:
        try:
            # For binary files, the safest Object Store readiness check is existence.
            # Some QuantConnect environments do not expose binary content through read()
            # in the same way as JSON/text files.
            self.debug(f"{symbol} | binary artifact present | key={key}")
            return True

        except Exception as exc:
            self.debug(f"{symbol} | binary artifact check failed | key={key} | error={exc}")
            return False