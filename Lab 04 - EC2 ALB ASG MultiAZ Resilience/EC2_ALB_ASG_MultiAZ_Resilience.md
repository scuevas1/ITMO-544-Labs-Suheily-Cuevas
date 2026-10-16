# EC2 S3 TwoTier FileUpload Display

## create_app_stack.sh output 
![create_app_stack.sh output](./screenshots/create_app_stack%20output.png)

## Successful Uploader Page
![Successful Uploader Page](./screenshots/successful%20uploader.png)

## Successful Viewer Page
![Successful Viewer page](./screenshots/successful%20viewer.png)

## Screenshot of aws elbv2 describe target health
![aws elbv2 describe target health](./screenshots/aws%20elbv2%20describe-target-health.png)

## CSV poll log and console output run that passed
https://github.com/scuevas1/cloud-computing-suheily/blob/main/testing/chaos_test_pass.csv


https://github.com/scuevas1/cloud-computing-suheily/blob/main/testing/chaos_test_passed_results.txt


## CSV poll log and console output from a run that failed
https://github.com/scuevas1/cloud-computing-suheily/blob/main/testing/chaos_test_failed.csv


https://github.com/scuevas1/cloud-computing-suheily/blob/main/testing/chaos_test_failed_results.txt

## using your own recovery-time numbers, what dominates the recovery window (health-check timing vs. boot/ npm install time vs. something else)

Waiting for the endpoint to come back up seemed to dominate the recovery window. The test first checked if the endpoint was healthy, which didn't take too long. Then it terminated the EC2 instance via the auto scaling group, which also seemed pretty quick. After that, it waited for the endpoint to go down and then come back up. I think this last part took the most time because the auto scaling group had to launch a new EC2 instance, the startup script had to install the npm packages, and the application had to start running again. The uploader took 66.7 seconds to recover and the viewer took 68.6 seconds. The uploader passed the 180 second SLO, but the viewer did not pass their 30 second SLO. I don't remember exactly how long each part took, but I think getting the new instances ready was the main reason the recovery took over a minute. 


## what changed in create_app_stack.sh / delete_app_stack.sh between the previous lab and this one — specifically, what replaced the old run-instances call and why.

In the previous lab, the create_app_stack.sh used the run-instances command to launch the EC2 instances directly. In this lab, that entire command was replaced with the auto scaling groups, so AWS could launch a new instance if one went down. Another change was adding the load balancer and target groups so traffic could be sent to the instances once they were healthy. For the delete_app_stack.sh I removed the commands that terminated the EC2 instances directly and replaced them with commands that delete the auto scaling groups instead. I also added commands to delete the load balancer and target groups.


## delete_app_stack.sh output
![delete_app_stack.sh output](./screenshots/delete-app-stack.png)


