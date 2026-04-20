#!/bin/bash

hitWebApp() {
  date
  for i in {1..15}; do
    curl -s http://localhost:5000/orders > /dev/null &
    curl -s http://localhost:5000/orders/$((RANDOM % 5 + 1)) > /dev/null &
    curl -s -X POST http://localhost:5000/orders/checkout > /dev/null &
  done
}


while [ 1 ] ; do
  sleep $((5 + RANDOM % 15)) && hitWebApp
  echo "---"
done
