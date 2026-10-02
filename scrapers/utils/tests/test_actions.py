import unittest

from ..actions import Rule, BaseCategorizer


class TestRule(unittest.TestCase):
    def test_match_returns_none_when_no_regex_matches(self):
        rule = Rule("Passed Senate", "passage")
        self.assertIsNone(rule.match("Referred to committee"))

    def test_match_returns_empty_attrs_when_matched_with_no_groups(self):
        rule = Rule("Passed Senate", "passage")
        self.assertEqual(rule.match("Passed Senate by voice vote"), {})

    def test_match_is_case_insensitive_by_default(self):
        rule = Rule("passed senate", "passage")
        self.assertEqual(rule.match("PASSED SENATE"), {})

    def test_match_collapses_flexible_whitespace(self):
        # a real-world case: action text upstream varies its whitespace
        # ("Referred to  Committee" vs "Referred to Committee"), so a
        # single space in the pattern should still match either.
        rule = Rule("Referred to Committee", "referral-committee")
        self.assertEqual(rule.match("Referred to   Committee"), {})

    def test_match_captures_named_groups_as_attrs(self):
        rule = Rule(r"Accompanied by (?P<bill_id>[SH]\d+)", [])
        attrs = rule.match("Accompanied by H123")
        self.assertEqual(attrs, {"bill_id": "H123"})

    def test_types_accepts_a_single_string(self):
        rule = Rule("Passed Senate", "passage")
        self.assertEqual(rule.types, {"passage"})

    def test_types_accepts_a_sequence(self):
        rule = Rule("Read third time and passed", ["passage", "reading-3"])
        self.assertEqual(rule.types, {"passage", "reading-3"})

    def test_extra_kwargs_become_attrs(self):
        rule = Rule("Signed by Speaker", "passage", actor="lower")
        self.assertEqual(rule.attrs, {"actor": "lower"})


class SampleCategorizer(BaseCategorizer):
    rules = [
        Rule(r"Referred to (?P<committees>.+)", "referral-committee"),
        Rule(r"Read third time and passed", ["passage", "reading-3"]),
        Rule(r"^Passed by indefinitely", "deferral", True),
        Rule(r"^Passed", "passage"),
    ]


class TestBaseCategorizer(unittest.TestCase):
    def setUp(self):
        self.categorizer = SampleCategorizer()

    def test_categorize_sets_classification_from_matched_rules(self):
        result = self.categorizer.categorize("Read third time and passed")
        self.assertEqual(set(result["classification"]), {"passage", "reading-3"})

    def test_categorize_merges_named_group_attrs(self):
        # finalize() only unwraps a single-item list for the special-cased
        # "actor" key; every other attr stays a list, even with one match.
        result = self.categorizer.categorize("Referred to Ways and Means")
        self.assertEqual(result["committees"], ["Ways and Means"])

    def test_categorize_with_no_matching_rule_has_empty_classification(self):
        result = self.categorizer.categorize("Some unrelated action text")
        self.assertEqual(result["classification"], [])

    def test_stop_rule_prevents_later_rules_from_also_matching(self):
        # "Passed by indefinitely" would also match the later, more general
        # "^Passed" rule if the categorizer kept going, so the "stop" flag on
        # the deferral rule must short-circuit the rest.
        result = self.categorizer.categorize("Passed by indefinitely")
        self.assertEqual(result["classification"], ["deferral"])


if __name__ == "__main__":
    unittest.main()


class TestRuleEdgeCases(unittest.TestCase):
    def test_flexible_whitespace_false_requires_exact_spacing(self):
        rule = Rule(
            "Referred to Committee", "referral-committee", flexible_whitespace=False
        )
        self.assertEqual(rule.match("Referred to Committee"), {})
        self.assertIsNone(rule.match("Referred to   Committee"))

    def test_flags_zero_makes_matching_case_sensitive(self):
        rule = Rule("Passed Senate", "passage", flags=0)
        self.assertEqual(rule.match("Passed Senate"), {})
        self.assertIsNone(rule.match("passed senate"))

    def test_compiled_regex_passes_through_untouched(self):
        import re as re_module

        compiled = re_module.compile(r"Passed Senate")
        rule = Rule(compiled, "passage")
        self.assertEqual(rule.match("Passed Senate"), {})

    def test_sequence_of_regexes_matches_when_any_match(self):
        rule = Rule(["Referred to Committee", "Passed Senate"], "passage")
        self.assertEqual(rule.match("Referred to Committee"), {})
        self.assertEqual(rule.match("Passed Senate"), {})

    def test_stop_flag_is_stored_on_the_rule(self):
        rule = Rule("Passed", "passage", True)
        self.assertTrue(rule.stop)


class UppercasingCategorizer(BaseCategorizer):
    rules = [Rule("PASSED SENATE", "passage")]

    def pre_categorize(self, text):
        return text.upper()


class PostHookCategorizer(BaseCategorizer):
    rules = [Rule("Passed Senate", "passage")]

    def post_categorize(self, return_val):
        return_val["source"] = "test"
        return return_val


class ActorCategorizer(BaseCategorizer):
    rules = [
        Rule(r"Passed by (?P<actor>\w+)", "passage"),
        Rule("Signed by Speaker", "passage", actor="lower"),
    ]


class TestBaseCategorizerHooks(unittest.TestCase):
    def test_pre_categorize_hook_transforms_text_before_matching(self):
        categorizer = UppercasingCategorizer()
        result = categorizer.categorize("passed senate")
        self.assertEqual(result["classification"], ["passage"])

    def test_post_categorize_hook_can_add_attrs(self):
        categorizer = PostHookCategorizer()
        result = categorizer.categorize("Passed Senate")
        self.assertEqual(result["source"], "test")

    def test_actor_named_group_unwraps_to_string(self):
        categorizer = ActorCategorizer()
        result = categorizer.categorize("Passed by senate")
        self.assertEqual(result["actor"], "senate")

    def test_rule_attrs_are_merged_into_result(self):
        categorizer = ActorCategorizer()
        result = categorizer.categorize("Signed by Speaker")
        self.assertEqual(result["actor"], "lower")

    def test_multiple_rules_union_their_types(self):
        class MultiRuleCategorizer(BaseCategorizer):
            rules = [
                Rule("Referred to Ways and Means", "referral-committee"),
                Rule("Ways and Means", "committee"),
            ]

        result = MultiRuleCategorizer().categorize("Referred to Ways and Means")
        self.assertEqual(
            set(result["classification"]), {"referral-committee", "committee"}
        )
