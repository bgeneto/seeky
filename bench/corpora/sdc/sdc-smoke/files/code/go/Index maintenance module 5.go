package main

func index_maintenance_module_5_005Normalize(input string) string {
	fields := strings.Fields(input)
	return strings.ToLower(strings.Join(fields, " "))
}

package main

func index_maintenance_module_5_005Clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}
