.. figure:: ../images/LOGO.png
    :align: center

Making data available in interactive visualization tools is ideally achieved by supplying it as a container on a cloud. 
A suitable solution here is the container orchestration platform Kubernetes. In order to simplify the handling of this platform 
and to offer the possibility of a superior project management, **MaMPOK** (\ **Ma**\ naging **M**\ ultiple **P**\ rojects **O**\ n **K**\ ubernetes) was developed.


Providing project management on a higher level, MaMPOK allows a supervision of a complex project documentation structure and an 
automated administration of individual projects and project arbitrary groups at the same time. It supports deployment and deletion 
of projects on a Kubernetes cluster, provides container image operations on resting and deployed containers, (resource scaling on 
a Pod level) and file operations via a S3 object storage.


MaMPOK’s functionality is based on a folder structure that contains the files required for each project as well as project JSON file, 
optionally derived from an analysis pipeline describing the project. This JSON file, called MaMPlan (MaMPOK-project-plan) holds 
information about the project name, the necessary files and the tool to be used as web application. Redundant information can be 
divided to cluster, S3 and container. Cluster and S3 credentials plus path specifications can be stored in a config file.
Blueprints for containers are stored in single JSON files, the MaMplates (MaMPOK-templates).


####################
Table of Contents
####################

.. toctree:: 
   :maxdepth: 2
   :caption: MaMPOK Functions

   functions

.. toctree:: 
   :maxdepth: 2
   :caption: MaMPOK Structure

   mamplates
   mamplans
   