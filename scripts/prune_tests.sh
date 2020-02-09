set -euo pipefail

timeout=120
log_file=log/prune_tests_failures.txt
data_dir=tests/data/openapi/json

function list_diff {
  f_one=$(mktemp)
  f_two=$(mktemp)
  echo -ne "$1" | sort > "$f_one"
  echo -ne "$2" | sort > "$f_two"
  comm -3 $f_one $f_two
}

# Skip passed tests
files=$(list_diff "$(grep 'Passed:' $log_file | cut -d ':' -f2- | tr -d ' ')" "$(ls $data_dir)")
# Skip max recursion hits
max_recursion_fails=$(grep ": Max reference recursion" log/test_results/fail_* | rev | cut -d ':' -f3 | rev | cut -d '/' -f3- | sed 's/fail_//' | tr '_' '.' | sed 's/\.txt//')
files=$(list_diff "$files" "$max_recursion_fails")
# Clear log file
curdate=$(date +%Y_%m_%d)
cp $log_file "$(echo -n $log_file | sed "s/prune/$curdate\_prune/")"
echo -n "" > $log_file
for file in $files
do
  echo "Testing file $file"
  set +e
  test_run=$(timeout $timeout pytest -qs --maxfail=1 --test_file $data_dir/$file 2>&1)
  ret=$?
  set -e
  if (($ret != 0))
  then
    if (($ret == 124))
    then
      echo "OpenAPI Schema Test Execution Timed Out: $file" | tee  -a $log_file
    fi
    echo "OpenAPI Schema Failed Tests: $file" | tee -a $log_file
    echo -ne "$test_run" > log/test_results/fail_$(echo -ne "$file" | tr '.' '_').txt
  else
    echo "OpenAPI Schema Tests Passed: $file" | tee -a $log_file
  fi
done
