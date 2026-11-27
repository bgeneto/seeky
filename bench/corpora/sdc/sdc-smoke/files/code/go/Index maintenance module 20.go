package main

func index_maintenance_module_20_020Clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}

package main

func index_maintenance_module_20_020Normalize(input string) string {
	fields := strings.Fields(input)
	return strings.ToLower(strings.Join(fields, " "))
}

package main

func index_maintenance_module_20_020Sum(values []int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}
