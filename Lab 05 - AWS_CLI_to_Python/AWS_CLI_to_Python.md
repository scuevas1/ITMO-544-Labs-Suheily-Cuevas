# AWS CLI to Python

## ls -a lab05 output 
![ls -a lab05 output](./screenshots/ls_-a_lab05_output.png)

## Screenshot of pytest
![SScreenshot of pytest](./screenshots/pytest_ss.png)

## Screenshot of "break it on purpose" experiment
![Screenshot of "break it on purpose" experiment](./screenshots/break_it_on_purpose_ss.png)

## Screenshot of python create_stack.py completing
![python create_stack.py completing](./screenshots/python_create_stack_ss.png)

## Screenshot of pytest -m integration -v
![pytest -m integration -v](./screenshots/pytest_-m_integration_-v_ss.png)

## Screenshot of pytest -m chaos -s output
![pytest -m chaos -s output](./screenshots/pytest_-m_chaos_-s_output.png)

## Screenshot of pytest -m chaos -s fail output
![pytest -m chaos -s fail output](./screenshots/pytest_-m_chaos_-s_fail_output.png)

## python delete_stack.py output #1
![python delete_stack.py output #1](./screenshots/python_delete_stack_ss1.png)

## python delete_stack.py output #2 (no errors)
![python delete_stack.py output #2](./screenshots/python_delete_stack_ss2.png)

## what moto proved, what it could not, and which tests cover the gap

Moto proved that the Python code was working correctly by testing how it created and deleted AWS resources without actually using AWS. One thing that I found useful was being able to test my code many times without worrying about creating any extra resources or instances. Something that Moto couldn't do was check if the load balancer was actually connecting to the EC2 instances correctly. Because of this, I had to run the integration test called test_every_target_becomes_healthy to make sure both the uploader and viewer instances were healthy and able to receive requests though the load balancer.


## Comparing ignore_errors("EntityAlreadyExists") with 2>/dev/null || true

The biggest difference between ignore_errors("EntityAlreadyExists") and 2>/dev/null || true is that the Bash version ignores all errors but the Python version only ignores specific errors. Another difference is that Bash makes it harder to figure out what went wrong since it hides the errors, while Python makes it easier by showing unexpected errors. 

## Reflect. Pick one place where the bash version was shorter than the Python version. Write two sentences on what the extra Python lines bought you.

One place where the Bash version was shorter was when creating the S3 bucket because it only checked if the bucket already existed before creating it. The Python version required more lines, but those extra lines allowed the code to check for specific errors instead of ignoring them, while also making sure the bucket was not publicly accessible. 