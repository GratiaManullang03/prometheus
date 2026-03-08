import logging
import random
import time
from functools import wraps

class LLMRetryHandler:
    def __init__(self, max_retries=5, initial_delay=1, max_delay=32, jitter=True):
        """
        Initialize the LLMRetryHandler with the given parameters.

        :param max_retries: The maximum number of retries.
        :param initial_delay: The initial delay in seconds.
        :param max_delay: The maximum delay in seconds.
        :param jitter: Whether to apply jitter to the delay.
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def __call__(self, func):
        """
        Wrap the given function with the retry logic.

        :param func: The function to wrap.
        :return: The wrapped function.
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = self.initial_delay
            for attempt in range(self.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < self.max_retries:
                        logging.warning(f"Attempt {attempt + 1} failed with error: {str(e)}")
                        if self.jitter:
                            delay_with_jitter = delay * random.uniform(0.5, 1.5)
                            time.sleep(min(delay_with_jitter, self.max_delay))
                        else:
                            time.sleep(min(delay, self.max_delay))
                        delay *= 2
                    else:
                        logging.error(f"All {self.max_retries + 1} attempts failed with error: {str(e)}")
                        raise
        return wrapper

# Example usage:
if __name__ == "__main__":
    retry_handler = LLMRetryHandler()

    @retry_handler
    def example_function():
        # Simulate a rate limit error
        import random
        if random.random() < 0.5:
            raise Exception("Rate limit error")
        return "Success"

    print(example_function())