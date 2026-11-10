# Navigation planning 

Open source autonomous lawn mower code: https://github.com/ClemensElflein/OpenMower?utm_source=chatgpt.com 

Coverage path planning: https://onlinelibrary.wiley.com/doi/full/10.1002/rob.22286?utm_source=chatgpt.com 

 
I think we use the wheel encoders, IMU and then like the rare earth magnets or some sort of localization camera thought ive never worked with one of those before 

 

we can use ROS2NAV2 which has waypoint following build in (this is giving similar to via points which seems like the best deterministic approach) like we know the pattern and the space we are traversing lets just find the best path mathematically  

 

Waypoint generator basically takes the pattern we would upload and turn it into fastening coordinates (x,y)   

 