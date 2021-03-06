"""
Trigger the creation of all individual CostAbroad price files
and a combined file including an overall category.
"""

from cost_abroad.create import create_price_files
from cost_abroad.combine import create_combined_file


categories = {
    "restaurant_hotel": "A0111",
    "recreation": "A0109",
    "transport": "A0107",
    "alcohol": "A010201",
    "food": "A010101",
}


def run(**kwargs):
    create_price_files(**kwargs)
    create_combined_file(**kwargs)

if __name__=='__main__':
    run(**categories)

