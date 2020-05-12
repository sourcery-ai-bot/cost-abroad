from io import StringIO
import unittest
from unittest.mock import patch, call

import responses
from pathlib import Path
from snapshot_test import DashSnapshotTestCase

import cost_abroad.create
import cost_abroad.filters
import cost_abroad.combine
import cost_abroad.run
import cost_abroad.visualise


URL = "http://ec.europa.eu/eurostat/wdds/rest/data/v2.1/json/en/prc_ppp_ind"


class CreateTests(unittest.TestCase):
    """Tests for the create module."""

    @patch("cost_abroad.create.create_price_file", spec=True)
    def test_create_price_files(self, mock_cpf):
        """Call create price file with two differnt categories."""
        cost_abroad.create.create_price_files(alcohol="A010201", transport="A0107")
        self.assertEqual(
            mock_cpf.mock_calls,
            [call("alcohol", "A010201"), call("transport", "A0107")],
        )

    @patch("cost_abroad.create.write_prices", spec=True)
    @patch(
        "cost_abroad.create.prices_raw",
        spec=True,
        return_value={
            "value": {"0": 77.8},
            "dimension": {
                "geo": {"category": {"index": {"AL": 0}, "label": {"AL": "Albania"}}}
            },
        },
    )
    def test_create_price_file(self, mock_pr, mock_wp):
        """Create price file returns list containing a tuple."""
        result = cost_abroad.create.create_price_file("food", "A010101")
        self.assertEqual(result, [("Albania", 77.8)])

    @patch("builtins.open")
    def test_write_prices_called_correctly(self, mock_op):
        """Write prices files called with correct category file name."""
        path = cost_abroad.create.Path(".\\data\\recreation.txt")
        cost_abroad.create.write_prices("recreation", [("Germany", 103.2)])
        open.assert_called_with(path, mode="w")

    @patch("cost_abroad.create.requests.get", spec=True)
    def test_get_is_called_correctly(self, get_js):
        """Get is called with correct URL and parameters."""
        cost_abroad.create.prices_raw("A0109")
        get_js.assert_called_with(
            URL,
            headers={"Accept": "application/json"},
            params={
                "na_item": "PLI_EU28",
                "lastTimePeriod": "1",
                "precision": "1",
                "ppp_cat": "A0109",
            },
        )

    @patch("cost_abroad.create.requests.get")
    def test_connection_error_suppressed(self, mock_get):
        """Default error text suppressed if connection error encountered."""
        mock_get.side_effect = cost_abroad.create.requests.exceptions.ConnectionError()
        self.assertIsNone(cost_abroad.create.prices_raw("A0111"))

    @responses.activate
    def test_correct_message_printed_if_no_data_in_response(self):
        """Correct console message printed if eurostat returns empty dataset."""
        responses.add(
            responses.GET, URL, body='{"error": "Dataset contains no data"}', status=400
        )
        with patch("sys.stdout", new=StringIO()) as mock_out:
            cost_abroad.create.prices_raw("invalidcodetest")
        self.assertIn("invalid category", mock_out.getvalue())

    @responses.activate
    def test_correct_message_printed_if_server_error(self):
        """Correct console message printed if server error returned."""
        responses.add(responses.GET, URL, status=500)
        with patch("sys.stdout", new=StringIO()) as mock_out:
            cost_abroad.create.prices_raw("A010101")
        self.assertIn("500 outside", mock_out.getvalue())

    @responses.activate
    def test_json_returned_if_valid_code_provided(self):
        """JSON is returned if valid price category given as argument."""
        responses.add(responses.GET, URL, body=r'{"value": {"0": 77}}')
        result = cost_abroad.create.prices_raw("A010201")
        self.assertEqual(result, {"value": {"0": 77}})


class FiltersTests(unittest.TestCase):
    """Tests for the filters module."""

    def test_filter_no_tidy(self):
        """List of tuples containing name and value should be returned."""
        snip = {
            "label": "Purchasing power parities (PPPs)",
            "source": "Eurostat",
            "class": "dataset",
            "value": {"0": 77.8, "1": 126.6, "2": 75.3},
            "dimension": {
                "geo": {
                    "category": {
                        "index": {"AL": 0, "AT": 1, "BA": 2},
                        "label": {
                            "AL": "Albania",
                            "AT": "Austria",
                            "BA": "Bosnia and Herzegovina",
                        },
                    }
                }
            },
        }

        filtered = cost_abroad.filters.filter_prices(snip)
        self.assertEqual(
            filtered,
            [("Albania", 77.8), ("Austria", 126.6), ("Bosnia and Herzegovina", 75.3)],
        )

    def test_filter_tidy_frg(self):
        """FRG should be replaced with Germany via tidy_countries."""
        snip = {
            "value": {"0": 77.8, "1": 126.6, "2": 102.4},
            "dimension": {
                "geo": {
                    "category": {
                        "index": {"AL": 0, "AT": 1, "DE": 2},
                        "label": {
                            "AL": "Albania",
                            "AT": "Austria",
                            "DE": "Germany (until 1990 former territory of the FRG)",
                        },
                    }
                }
            },
        }

        tdy_frg = cost_abroad.filters.filter_prices(snip)
        self.assertEqual(
            tdy_frg, [("Albania", 77.8), ("Austria", 126.6), ("Germany", 102.4)]
        )

    def test_filter_tidy_candidate(self):
        """Candidate should be replaced with Exclude via tidy_countries."""
        snip = {
            "value": {"0": 77.8, "1": 75.3, "2": 74.4},
            "dimension": {
                "geo": {
                    "category": {
                        "index": {"AL": 0, "BA": 1, "CPC1": 2},
                        "label": {
                            "AL": "Albania",
                            "BA": "Bosnia and Herzegovina",
                            "CPC1": "Candidate and potential candidate countries "
                            "except Turkey and Kosovo (under United Nations "
                            "Security Council Resolution 1244/99)",
                        },
                    }
                }
            },
        }

        tdy_can = cost_abroad.filters.filter_prices(snip)
        self.assertEqual(
            tdy_can,
            [("Albania", 77.8), ("Bosnia and Herzegovina", 75.3), ("Exclude", 74.4)],
        )


class CombineTests(unittest.TestCase):
    """Tests for the combine_cost_abroad module."""

    def setUp(self):
        self.cdata = [
            [["Malta", 77.8], ["Poland", 75.3]],
            [["Malta", 64.4], ["Poland", 69.1]],
            [["Malta", 50.2], ["Poland", 60.4]],
            [["Malta", 80.9], ["Poland", 49.3]],
            [["Malta", 62.1], ["Poland", 63.1]],
        ]

        self.combi = {
            "food": [["Malta", 77.8], ["Poland", 75.3]],
            "alcohol": [["Malta", 64.4], ["Poland", 69.1]],
            "transport": [["Malta", 50.2], ["Poland", 60.4]],
            "recreation": [["Malta", 80.9], ["Poland", 49.3]],
            "restaurant_hotel": [["Malta", 62.1], ["Poland", 63.1]],
            "overall": [("Malta", 67.1), ("Poland", 63.4)],
        }

    @patch("json.load", spec=True)
    @patch("builtins.open", spec=True)
    def test_create_combined_file_one_cat(self, mock_op, mock_js):
        """Test one price categories combined with overall."""
        mock_js.side_effect = [self.cdata[0]]
        result = cost_abroad.combine.create_combined_file(food="A010101")
        self.assertEqual(
            result,
            {
                "food": [["Malta", 77.8], ["Poland", 75.3]],
                "overall": [("Malta", 77.8), ("Poland", 75.3)],
            },
        )

    @patch("json.load", spec=True)
    @patch("builtins.open", spec=True)
    def test_create_combined_file_two_cats(self, mock_op, mock_js):
        """Test two price categories combined with overall."""
        mock_js.side_effect = self.cdata[0:2]
        result = cost_abroad.combine.create_combined_file(food="A010101", alcohol="A010201")
        self.assertEqual(
            result,
            {
                **{k: v for k, v in self.combi.items() if k in ("food", "alcohol")},
                **{"overall": [("Malta", 71.1), ("Poland", 72.2)]},
            },
        )

    @patch("json.load", spec=True)
    @patch("builtins.open", spec=True)
    def test_create_combined_file_all_cats(self, mock_op, mock_js):
        """Test all price categories combined with overall."""
        mock_js.side_effect = self.cdata
        result = cost_abroad.combine.create_combined_file(
            food="A010101",
            alcohol="A010201",
            transport="A0107",
            recreation="A0109",
            restaurant_hotel="A0111",
        )
        self.assertEqual(result, self.combi)

    @patch("builtins.open", spec=True)
    def test_combined_write_called_correctly(self, mock_op, spec=True):
        """Combined write called with correct file name."""
        path = cost_abroad.combine.Path(".\\data\\combined.txt")
        cost_abroad.combine.combined_write(
            {
                "food": [["Albania", 77.8], ["Bosnia and Herzegovina", 75.3]],
                "overall": [("Albania", 77.8), ("Bosnia and Herzegovina", 75.3)],
            }
        )
        open.assert_called_with(path, mode="w")


class RunTest(unittest.TestCase):
    """Test for the run_files module."""

    @patch("cost_abroad.run.create_price_files", spec=True)
    @patch("cost_abroad.run.create_combined_file", spec=True)
    def test_create_and_combined_called_correctly(self, mock_cf, mock_pf):
        """Test category file and combined file functions called correctly."""
        cost_abroad.run.run(**cost_abroad.run.categories)
        cost_abroad.run.create_price_files.assert_called_with(
            food="A010101",
            alcohol="A010201",
            transport="A0107",
            recreation="A0109",
            restaurant_hotel="A0111",
        )
        cost_abroad.run.create_combined_file.assert_called_with(
            food="A010101",
            alcohol="A010201",
            transport="A0107",
            recreation="A0109",
            restaurant_hotel="A0111",
        )


class VisualiseTests(DashSnapshotTestCase):
    """Test for the visualise module."""

    def test_html_snapshot_matches_reference(self):
        """Test Dash app html snapshot matches reference snapshot."""
        my_component = cost_abroad.visualise.app.layout
        # Increment id to recreate snapshot when running test
        self.assertSnapshotEqual(my_component, "id-005")

    def test_choropleth_contains_country_list_excerpt(self):
        """Test update_figure passing country list entries to choropleth."""
        # Excerpt includes entries dependent on filter's tidy function
        excerpt = (
            '"Exclude", "Finland", "France", "Germany", '
            '"Greece", "Hungary", "Iceland", "Ireland", "Italy", '
            '"Latvia", "Lithuania", "Luxembourg", "Malta", '
            '"Montenegro", "Netherlands", "North Macedonia", '
            '"Norway", "Poland", "Portugal", "Romania", "Serbia", '
            '"Slovakia", "Slovenia", "Spain", "Sweden", '
            '"Switzerland", "Turkey", "United Kingdom"'
        )
        result = cost_abroad.visualise.update_figure("overall")
        self.assertIn(excerpt, result)


if __name__ == "__main__":
    unittest.main()
