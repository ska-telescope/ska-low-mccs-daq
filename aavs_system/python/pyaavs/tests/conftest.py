import pytest
import logging
import re

def pytest_addoption(parser):
    parser.addoption("--test_config", action="store", default=None)
    parser.addoption("--config", action="store", default=None)
    parser.addoption("--init", action="store_true")
    parser.addoption("--init_only", action="store_true")


@pytest.fixture
def get_param(request):
    config_param = {"test_config": request.config.getoption("--test_config"),
                    "config": request.config.getoption("--config"),
                    "init": request.config.getoption("--init"),
                    "init_only": request.config.getoption("--init_only")
                    }
    return config_param


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Produces custom summary at the end of the tests
    """

    # removes all but pytest logger
    for handler in logging.root.handlers[:-2]:
        logging.root.removeHandler(handler)

    reports = terminalreporter.getreports('passed') + terminalreporter.getreports('failed') + terminalreporter.getreports('skipped')

    results_dict = {}

    for report in reports:
        # get test name
        full_test_name = report.nodeid.split("::")[-1]
        test_name_in_square_brackets = re.findall(r'\[([A-Za-z0-9_]+)\]', full_test_name)

        if len(test_name_in_square_brackets) != 0:
            # if it is parametrized, set name to TEST_{parametrized name, all to upper case}
            short_test_name = f"TEST_{test_name_in_square_brackets[0].upper()}"
        else:
            # if not just set name to test name all to upper case
            short_test_name = full_test_name.upper()

        results_dict[short_test_name] = report.outcome.upper()

    # get max length of test name
    max_length = len(max(results_dict.keys(), key=len)) + 1

    for test in results_dict:
        
        # Pad test name with spaces to line up results
        spaces = max_length - len(test)
        test_name = f"{test}{''.join([' ']*spaces)}"
        test_results = results_dict[test]

        # Log results at correct level
        if test_results == "PASSED":
            logging.info(f"{test_name}: {test_results}")
        elif test_results == "SKIPPED":
            logging.warning(f"{test_name}: {test_results}")
        else:
            logging.error(f"{test_name}: {test_results}")

    pass_num = len(terminalreporter.getreports('passed'))
    skip_num = len(terminalreporter.getreports('skipped'))
    fail_num = len(terminalreporter.getreports('failed'))

    if skip_num == 0 and fail_num == 0:
        logging.info("ALL TEST PASSED!")
    elif pass_num != 0:
        logging.info(f"{pass_num} TESTS PASSED!")

    if fail_num != 0:
        logging.error(f"{fail_num} TESTS FAILED!")

    if skip_num != 0:
        logging.warning(f"{skip_num} TESTS SKIPPED!")
