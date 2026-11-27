package main

func index_maintenance_module_3_003Sum(values []int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}

package main

func index_maintenance_module_3_003Clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}
