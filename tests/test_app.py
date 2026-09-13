import base64
import importlib.util
import sys
import unittest
import zipfile
from pathlib import Path


APP_PATH = Path(__file__).parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("course_ranker", APP_PATH)
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


class ParserTests(unittest.TestCase):
    def test_static_data_is_loaded(self):
        self.assertGreater(len(app.COURSE_INDEX), 100)

    def test_fuzzy_course_search(self):
        matches = app.search_courses("量子算法")
        self.assertTrue(matches)
        self.assertEqual(matches[0]["name"], "量子算法")

    def test_ranking_is_descending(self):
        result = app.rank_course({"name": "量子算法"})
        scores = [row["average"] for row in result["rankings"] if row["average"] is not None]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_filters_course_candidates(self):
        self.assertEqual(app.course_candidates(["课程名称", "高等数学", "3.0", "大学物理"]), ["高等数学", "大学物理"])

    def test_parses_csv_import(self):
        data = base64.b64encode("课程名称\n高等数学\n大学物理\n".encode()).decode()
        self.assertEqual(app.parse_import("plan.csv", data), ["高等数学", "大学物理"])

    def test_course_metadata_has_credits_and_categories(self):
        # Verify that courses in index have valid credits and category fields
        course = next(iter(app.COURSE_INDEX.values()))
        self.assertIn("credits", course)
        self.assertGreater(course["credits"], 0)
        self.assertIn("category_l1", course)
        self.assertIn("category_l2", course)
        self.assertIn(course["category_l1"], app.CATEGORY_HIERARCHY)
        self.assertIn("classes", course)
        self.assertGreater(len(course["classes"]), 0)

    def test_category_classification_hierarchy(self):
        # Check standard representative courses
        l1, l2 = app.classify_course("思想道德与法治", {"马克思主义学院"})
        self.assertEqual((l1, l2), ("通识课程", "思政理论类"))

        l1, l2 = app.classify_course("大学体育（一）", {"公共体育与艺术部"})
        self.assertEqual((l1, l2), ("通识课程", "军体素养类"))

        l1, l2 = app.classify_course("微积分（甲）I", {"数学科学学院"})
        self.assertEqual((l1, l2), ("大类基础课程", "数理基础类"))

        l1, l2 = app.classify_course("数据结构与算法", {"计算机科学与技术学院"})
        self.assertEqual((l1, l2), ("专业课程", "计算机与人工智能类"))

        l1, l2 = app.classify_course("生产实习", {"建筑工程学院"})
        self.assertEqual((l1, l2), ("实践与创新课程", "专业实验与实践实习"))

    def test_credit_inference(self):
        cr_pe = app.infer_credits("大学体育（一）", "通识课程", "军体素养类")
        self.assertEqual(cr_pe, 1.0)

        cr_calc = app.infer_credits("微积分（甲）I", "大类基础课程", "数理基础类")
        self.assertEqual(cr_calc, 5.0)

        cr_marx = app.infer_credits("马克思主义基本原理", "通识课程", "思政理论类")
        self.assertEqual(cr_marx, 3.0)

    def test_timetable_embedding_and_sorting(self):
        # 1. Without timetable restriction
        res_all = app.filter_courses(selected_slots=None, page=1, page_size=20)
        self.assertGreater(res_all["total_courses"], 1000)

        # Confirm that remaining max GPA is strictly descending
        gpas = [c["max_gpa"] for c in res_all["courses"] if c["max_gpa"] is not None]
        self.assertEqual(gpas, sorted(gpas, reverse=True))

        # 2. Narrow slot restriction: only Monday morning slots [1, 1] and [1, 2]
        res_narrow = app.filter_courses(selected_slots=[[1, 1], [1, 2]], page=1, page_size=20)
        self.assertGreater(res_narrow["total_courses"], 0)
        self.assertLess(res_narrow["total_courses"], res_all["total_courses"])

        # Every class in the filtered courses must be embedded in [[1, 1], [1, 2]]
        allowed_set = {(1, 1), (1, 2)}
        for c in res_narrow["courses"]:
            for cls in c["classes"]:
                cls_slots = {(s[0], s[1]) for s in cls["slots"]}
                self.assertTrue(cls_slots.issubset(allowed_set))

    def test_sample_count_threshold(self):
        # Filter with min_samples = 50
        res_high_samples = app.filter_courses(min_samples=50, page=1, page_size=30)
        self.assertGreater(res_high_samples["total_courses"], 0)
        for c in res_high_samples["courses"]:
            for cls in c["classes"]:
                cnt = app.count_value(cls.get("total_count"))
                self.assertGreaterEqual(cnt, 50)

    def test_categories_tree(self):
        tree = app.get_categories_tree()
        self.assertEqual(len(tree["hierarchy"]), 4)
        self.assertGreater(tree["total_courses"], 1000)
        for l1 in tree["hierarchy"]:
            self.assertIn(l1, tree["counts"])
            self.assertGreater(tree["counts"][l1]["total"], 0)

    def test_search_and_rank_return_credits(self):
        matches = app.search_courses("微积分")
        self.assertTrue(matches)
        self.assertIn("credits", matches[0])
        self.assertGreater(matches[0]["credits"], 0)

        rank_res = app.rank_course({"name": matches[0]["name"]})
        self.assertIn("credits", rank_res)
        self.assertGreater(rank_res["credits"], 0)

    def test_exclude_keyword(self):
        # Inclusion only
        res_all_calc = app.filter_courses(keyword="微积分")
        total_calc = res_all_calc["total_courses"]
        self.assertGreater(total_calc, 0)

        # Exclude "乙"
        res_no_yi = app.filter_courses(keyword="微积分", exclude_keyword="乙")
        self.assertLess(res_no_yi["total_courses"], total_calc)
        for c in res_no_yi["courses"]:
            self.assertNotIn("乙", c["name"])

        # Multiple exclusion tokens
        res_multi_exclude = app.filter_courses(exclude_keyword="实验, 体育")
        for c in res_multi_exclude["courses"]:
            self.assertNotIn("实验", c["name"])
            self.assertNotIn("体育", c["name"])

    def test_all_listed_times_must_be_embedded(self):
        # When selecting only Monday periods 1-5, every qualified class must have ALL its slots within Monday 1-5
        selected_monday = [[1, 1], [1, 2], [1, 3], [1, 4], [1, 5]]
        allowed_set = {(1, 1), (1, 2), (1, 3), (1, 4), (1, 5)}
        res = app.filter_courses(selected_slots=selected_monday, page=1, page_size=50)
        self.assertGreater(res["total_courses"], 0)
        for c in res["courses"]:
            for cls in c["classes"]:
                cls_slots = {(s[0], s[1]) for s in cls["slots"]}
                # Ensure every single listed slot is within the allowed_set
                self.assertTrue(cls_slots.issubset(allowed_set))
                # Ensure no class has slots outside Monday 1-5
                for s in cls["slots"]:
                    self.assertEqual(s[0], 1)
                    self.assertIn(s[1], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
