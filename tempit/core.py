import time
import warnings
from collections import deque
from functools import partial, wraps
from threading import Lock
from typing import Any, Callable, Dict, List, Tuple

from .utils import print_tempit_values, show_error


def tempit(
    *args: Any,
    run_times: int = 1,
    concurrent_execution: bool = True,
    verbose: bool = False,
    check_for_recursion: bool | None = None,
) -> Callable:
    """
    Decorator function that measures the execution time of a given function. It can be called like @tempit or using arguments @tempit(...)

    Args:
        args: contains the function to be decorated if no arguments are provided when calling the decorator
        run_times (int, optional): The number of times the function should be executed. Defaults to 1.
        concurrent_execution (bool, optional): This parameter will allow for the concurrent execution of the function using joblib.
                                               The default execution backend is "loky" but if the function is being triggered other than the main thread or main process, the backend will be changed to multithreading.
                                               If the execution of the concurrency fails, it will try to execute the func run_times non concurrently in the main process.
                                               Defaults to True.
        verbose (bool, optional): Whether to print detailed information after execution. Defaults to False.

    Returns:
        Callable: The decorated function if arguments are provided, otherwise a partial function.

    Raises:
        RuntimeError: If the concurrency mode fails, the function is executed in the main process.

    Notes:
        - If `run_times` is less than 1, it will be set to 1.
        - If the function is a method, the first argument will be removed from `args_to_print`.
        - If the function is a class method, the first argument will be replaced with the class itself.
        - If the function is a static method, the first argument will be removed.

    Example:
        @tempit(run_times=5, concurrent_execution=True, verbose=True)
        def my_function(arg1, arg2):
            # function body

        @tempit
        def my_function(arg1, arg2):
            # function body

        # The decorated function can be used as usual
        result = my_function(arg1_value, arg2_value)
    """
    if check_for_recursion is not None:
        warning_msg = "check_for_recursion is deprecated and will be removed in future versions."
        warnings.warn(warning_msg, DeprecationWarning, stacklevel=2)

    def decorator(
        func: Callable, run_times: int = 1, concurrent_execution: bool = True, verbose: bool = False
    ) -> Callable:

        potential_recursion_func_stack: deque[Callable] = deque()
        is_recursive: bool = False
        time_wasted_lock: Lock = Lock()
        time_wasted: float = 0

        @wraps(func)
        def tempit_wrapper(*args: Tuple, **kwargs: Dict) -> Any:
            nonlocal potential_recursion_func_stack
            nonlocal is_recursive
            nonlocal time_wasted

            start_time = time.perf_counter()
            run_times_final, concurrent_execution_final, is_recursive = check_is_recursive_func(
                func, run_times, concurrent_execution, potential_recursion_func_stack
            )
            callable_func, args, args_to_print = extract_callable_and_args_if_method(func, *args)

            if is_recursive:  # If the function is recursive, it will be executed directly
                end_time = time.perf_counter()
                with time_wasted_lock:  # Update the time non-ocurring in the function execution
                    time_wasted += end_time - start_time
                try:
                    result = func(*args, **kwargs)
                except Exception as e:
                    show_error(e, filename=__file__)
                    result = None

                potential_recursion_func_stack.pop()
                return result

            result, total_times, real_time = function_execution(
                callable_func, run_times_final, concurrent_execution_final, *args, **kwargs
            )

            wasted_time_avg = time_wasted / len(total_times)
            total_times = [x - wasted_time_avg for x in total_times]

            potential_recursion_func_stack.pop()
            if not potential_recursion_func_stack:  # The function is not recursive at the moment, so it will be printed
                print_tempit_values(
                    run_times_final, verbose, callable_func, total_times, real_time, *args_to_print, **kwargs
                )

            return result

        return tempit_wrapper

    if args:  # If arguments are not provided, return a decorator
        return decorator(*args, run_times=run_times, concurrent_execution=concurrent_execution, verbose=verbose)

    else:  # Otherwise, return a partial function
        return partial(decorator, run_times=run_times, concurrent_execution=concurrent_execution, verbose=verbose)


def check_is_recursive_func(
    func: Callable, run_times: int, concurrent_execution: bool, potential_recursion_func_stack: deque[Callable]
) -> Tuple[int, bool, bool]:
    """
    Checks if the function is being called recursively.
    Returns:
        Tuple[List[Callable], int, bool]: A tuple containing the potential recursive function stack to check if the function is being called recursively, None otherwise.
        The second element is the run_times parameter, and the third element is a boolean indicating if concurrent_execution is enabled.
    """

    if potential_recursion_func_stack and potential_recursion_func_stack[-1] == func:
        potential_recursion_func_stack.append(func)
        # Check if the function is being called recursively by checking the object identity. This is way faster than using getFrameInfo
        warning_msg = "Recursive function detected. This process may be slow. To improve performance, consider wrapping the recursive function in another function and applying the @tempit decorator to the new function."
        warnings.warn(warning_msg, stacklevel=3)
        return 1, False, True
    potential_recursion_func_stack.append(func)
    return run_times, concurrent_execution, False


def extract_callable_and_args_if_method(func: Callable, *args: Tuple) -> Tuple[Callable, Tuple, Tuple]:
    """
    Extracts the callable function and arguments from a given function, if it is a method.
    Args:
        func (Callable): The function to extract the callable from.
        args: Variable length argument list.
    Returns:
        Tuple[Callable, Tuple, Tuple]: A tuple containing the extracted callable function, the modified arguments,
        and the arguments to be printed.
    Raises:
        None
    """
    callable_func = func
    args_to_print = args
    is_method = hasattr(args[0], func.__name__) if args else False

    if isinstance(func, type):
        pass  # It is a class. It will raise a pickle exception if it is triggered from a new process

    if is_method:
        args_to_print = args[1:]
        if isinstance(func, classmethod):
            args = (args[0].__class__,) + args[1:]  # type: ignore
            callable_func = func.__func__
        elif isinstance(func, staticmethod):
            args = args[1:]

    return callable_func, args, args_to_print


def function_execution(
    callable_func: Callable, run_times: int, concurrent_execution: bool, *args: Tuple, **kwargs: Dict
) -> Tuple[Any, List[float], float]:
    """
    Run and measure the execution time of a function. It also returns the value of the function return and the execution times.
    Args:
        callable_func (Callable): The function to be executed.
        run_times (int): The number of times the function should be executed.
        concurrency_mode (str): The concurrency mode for executing the function.
        *args (Tuple): The positional arguments to be passed to the function.
        **kwargs (Dict): The keyword arguments to be passed to the function.
    Returns:
        Tuple[Any, List[float], float]: A tuple containing the result of the function,
        a list of execution times for each run, and the total real time taken.
    """

    if run_times < 1:
        run_times = 1
    start_time = time.perf_counter()
    if run_times > 1 and concurrent_execution:
        try:
            result, total_times = tempit_with_concurrency(callable_func, run_times, *args, **kwargs)
        except RuntimeError as e:
            show_error(e, filename=__file__)
            result, total_times = tempit_main_process(callable_func, run_times, *args, **kwargs)
    else:
        result, total_times = tempit_main_process(callable_func, run_times, *args, **kwargs)
    end_time = time.perf_counter()
    real_time = end_time - start_time
    return result, total_times, real_time


def tempit_main_process(func: Callable, run_times: int, *args: Tuple, **kwargs: Dict) -> Tuple[Any, List[float]]:
    """
    Run and measure the execution time of a function in the main process. It also returns the value of the function return and the execution times.
    Args:
        func (Callable): The function to be executed.
        run_times (int): The number of times the function should be executed.
        *args (Tuple): The positional arguments to be passed to the function.
        **kwargs (Dict): The keyword arguments to be passed to the function.
    Returns:
        Tuple[Any, List[float]]: A tuple containing the result of the function and a list of execution times for each run.
    """

    total_times: List[float] = []
    for _ in range(run_times):
        start_time: float = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            show_error(e, filename=__file__)
            result = None
        finally:
            end_time: float = time.perf_counter()
            total_times.append((end_time - start_time))
    return result, total_times


def tempit_with_concurrency(func: Callable, run_times: int, *args: Tuple, **kwargs: Dict) -> Tuple[Any, List[float]]:
    """
    Executes a given function concurrently a specified number of times using joblib.

    Args:
        func (Callable): The function to be executed.
        run_times (int): The number of times the function should be executed.
        *args (Tuple): The positional arguments to be passed to the function.
        **kwargs (Dict): The keyword arguments to be passed to the function.

    Returns:
        Tuple[Any, List[float]]: A tuple containing the result of the function and a list of execution times for each run.
        If an exception was raised in one of the concurrent tasks, the function will raise a RuntimeError and returns control
        to the main process, then the function will be executed in the main process non-concurrently.
    """

    from multiprocessing import current_process
    from os import cpu_count
    from pickle import PicklingError
    from threading import current_thread

    from joblib import Parallel, delayed

    def run_func(
        func: Callable,
        *args: Tuple,
        **kwargs: Dict,
    ) -> Tuple[Any, float, bool]:
        has_crashed: bool = False
        start_time = time.perf_counter()
        try:
            result: Any = func(*args, **kwargs)
        except Exception:
            has_crashed = True
            result = None
        finally:
            end_time = time.perf_counter()
        return result, end_time - start_time, has_crashed

    EXCEPTION_MESSAGE = (
        "An exception was raised in one of the concurrent jobs. Trying to execute in the main process non-concurrently."
    )

    joblib_backend = None  # Default backend for joblib
    # Rule of thumb, use at least 2 workers or at least the number of cores minus 1.
    # It is not ideal for multithreading, but it will make good balance
    workers: int = max(2, cpu_count() - 1) if cpu_count() is not None else 2  # type: ignore

    if current_process().name != "MainProcess" or current_thread().name != "MainThread":
        joblib_backend = "threading"  # If we are running in other than the main process or main thread, use threading instead of multiprocessing

    try:
        results: List[Tuple[Any, float, bool]] = Parallel(n_jobs=workers, backend=joblib_backend)(
            delayed(run_func)(func, *args, **kwargs) for _ in range(run_times)
        )  # type: ignore

    except PicklingError:  # If a pickle error is raised, use threading instead of multiprocessing
        joblib_backend = "threading"
        try:
            results: List[Tuple[Any, float, bool]] = Parallel(n_jobs=workers, backend=joblib_backend, prefer="threads")(
                delayed(run_func)(func, *args, **kwargs) for _ in range(run_times)
            )  # type: ignore

        except Exception:
            raise RuntimeError(EXCEPTION_MESSAGE)

    except Exception:
        raise RuntimeError(EXCEPTION_MESSAGE)

    if any(has_crashed for _, _, has_crashed in results):  # This code will be deprecated soon
        raise RuntimeError(EXCEPTION_MESSAGE)

    total_times = [total_time for _, total_time, has_crashed in results if not has_crashed]
    result = results[0][0]
    return result, total_times
