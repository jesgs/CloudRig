from typing import Dict
from ..generation.troubleshooting import CloudLogManager

import time

class CloudPerformanceProfilerMixin:
	"""Class to help keep track of cumulative time that it takes a single 
	rig element to execute various tasks."""
	def init_timer(self):
		self.init_time = time.time()
		self.timer_started = -1
		self.timer_running = False # Just for sanity checking pause/continue calls.
		self.durations: Dict[str, float] = {}

	@property
	def total_time(self) -> float:
		total = sum(self.durations.values())
		if self.timer_running:
			total += time.time() - self.timer_started
		return total

	def continue_timer(self):
		"""Mark the timer as running and save the current time as a point of reference."""
		assert not self.timer_running, "Can't continue the timer when it's already running."
		self.timer_started = time.time()
		self.timer_running = True

	def pause_timer(self, duration_name="") -> float:
		"""Pause the timer and return the total time accumulated for a given Duration Name."""
		assert self.timer_running, "Can't pause the timer when it's not running."
		self.timer_running = False
		duration = time.time() - self.timer_started
		if duration_name == "":
			duration_name = "Duration " + str(len(self.durations))
		if duration_name not in self.durations:
			self.durations[duration_name] = duration
		else:
			self.durations[duration_name] += duration
		return self.durations[duration_name]

	def timer_to_log(self, logger: CloudLogManager, threshold=0.009) -> str:
		if self.total_time < threshold:
			return
		self.add_log("Time: " + str(self.total_time)
			,description = "\n".join([f"{name}: {time}" for name, time in self.durations.items()])
		)