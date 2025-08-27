import random
import time
import pygame
import carla
import numpy as np
import json
import os
import math

from agents.navigation.behavior_agent import BehaviorAgent
from agents.navigation.local_planner import RoadOption

# Global variables for collision debounce
_last_collision_time = {}
COLLISION_DEBOUNCE_TIME = 2.0  # Seconds: INCREASED to avoid
# multiple registrations of the same collision

# Global variables for weather management
LAST_WEATHER_CHANGE_TIME = 0
WEATHER_CHANGE_INTERVAL = 10  # Seconds: change weather every
# X seconds.

# Global variable to control execution state
# Will be set to False to terminate the simulation
running = True


def get_town_static_characteristics(world, carla_map):  # Pass world directly
    """
    Analyzes the CARLA map to extract static characteristics like
    the number of traffic lights and an approximation of curves.
    """
    print("Gathering town static characteristics...")
    traffic_lights = 0
    num_curves = 0
    num_junctions = 0
    num_roads = 0
    road_ids = set()

    waypoints = carla_map.generate_waypoints(2.0)  # Generate waypoints with 2.0 meter resolution

    for waypoint in waypoints:
        if waypoint.is_junction:
            num_junctions += 1

        if waypoint.road_id not in road_ids:
            num_roads += 1
            road_ids.add(waypoint.road_id)

        # Approximate curves by checking the change in orientation over a short distance
        # A significant change in yaw indicates a curve
        if waypoint.next(5.0):  # Check 5 meters ahead
            next_waypoint = waypoint.next(5.0)[0]
            angle_diff = abs(waypoint.transform.rotation.yaw - next_waypoint.transform.rotation.yaw)
            if angle_diff > 10 and angle_diff < 350:  # A threshold to detect a curve (e.g., more than 10 degrees)
                num_curves += 1

    # Count traffic lights by iterating through all actors and filtering by type
    world_actors = world.get_actors()  # Corrected: Use 'world' object
    for actor in world_actors:
        if 'traffic_light' in actor.type_id:
            traffic_lights += 1

    # Remove duplicates for junctions, as multiple waypoints can be in one junction
    num_junctions = len(set(wp.junction_id for wp in waypoints if wp.is_junction))

    # Simple heuristic to reduce overcounting curves: Divide by a factor based on waypoint density
    # This is still an approximation, more sophisticated curve detection would be needed for precision
    num_curves = int(num_curves / 15)

    return {
        "map_name": carla_map.name,
        "traffic_lights": traffic_lights,
        "approx_curves": num_curves,
        "approx_junctions": num_junctions,
        "approx_roads": num_roads
    }


def is_collision_on_curve(collision_location, carla_map):
    """
    Determines if a collision occurred on a straight road or a curve.
    This is an approximation based on waypoint curvature.
    """
    waypoint = carla_map.get_waypoint(collision_location, project_to_road=True)
    if not waypoint:
        return "unknown"

    # Check the curvature of the road at the collision point
    # A simple way is to check the angle difference between consecutive waypoints
    # further down the road.
    if waypoint.next(10.0):  # Check 10 meters ahead for curvature
        next_waypoint = waypoint.next(10.0)[0]
        angle_diff = abs(waypoint.transform.rotation.yaw - next_waypoint.transform.rotation.yaw)

        # If the angle difference is significant, it's likely a curve
        if angle_diff > 5:  # Threshold in degrees for detecting a curve
            return "curve"
    return "straight"


def main():
    # Clean up global
    # collision and weather tracking for each new run.
    global _last_collision_time, LAST_WEATHER_CHANGE_TIME, running
    _last_collision_time.clear()
    LAST_WEATHER_CHANGE_TIME = 0
    running = True  #
    # Ensure it's True at the start of each run

    pygame.init()
    display = pygame.display.set_mode((1280, 720), pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.display.set_caption("CARLA: Advanced Traffic Scenario")
    clock = pygame.time.Clock()

    client = carla.Client('127.0.0.1', 2000)
    client.set_timeout(30.0)

    # Updated list of
    # valid towns
    town_list = ['Town01', 'Town02', 'Town03', 'Town04', 'Town05']
    town = random.choice(town_list)
    print(f"🌍 Loaded map: {town}")
    client.load_world(town)
    time.sleep(3.0)  #
    # Wait for the world to fully load

    world = client.get_world()
    carla_map = world.get_map()  # Renamed 'map' to 'carla_map' to avoid shadowing built-in 'map'
    traffic_manager = client.get_trafficmanager(8000)
    traffic_manager.set_synchronous_mode(False)
    traffic_manager.set_global_distance_to_leading_vehicle(0.8)
    traffic_manager.global_percentage_speed_difference(-20.0)

    # Get static town characteristics once at the beginning
    town_characteristics = get_town_static_characteristics(world, carla_map)  # Pass world here
    print(f"Town Characteristics: {json.dumps(town_characteristics, indent=4)}")

    blueprint_library = world.get_blueprint_library()
    all_vehicle_bps = blueprint_library.filter('vehicle.*')

    # Exclude buses,
    # trucks, bikes, and motorcycles from ego vehicles
    ego_vehicle_bps = [bp for bp in all_vehicle_bps if 'bus' not in bp.id and 'truck' not in bp.id
                       and 'bike' not in bp.id and 'motorcycle' not in bp.id]

    traffic_vehicle_bps = all_vehicle_bps

    walker_bp = blueprint_library.filter('walker.pedestrian.*')
    walker_controller_bp = blueprint_library.find('controller.ai.walker')

    camera_bp = blueprint_library.find('sensor.camera.rgb')
    camera_bp.set_attribute('image_size_x', '1280')
    camera_bp.set_attribute('image_size_y', '720')
    camera_bp.set_attribute('fov', '90')

    spawn_points = carla_map.get_spawn_points()
    random.shuffle(spawn_points)

    print("🧹 Cleaning up previous actors...")
    for actor in world.get_actors():
        if 'vehicle' in actor.type_id or 'sensor' in actor.type_id or 'walker' in actor.type_id or \
                'controller.ai.walker' in actor.type_id:
            try:
                actor.destroy()
            except Exception as e:
                print(f"Error destroying {actor.type_id} (ID: {actor.id}): {e}")
    time.sleep(1.0)  #
    # Give time for destruction

    if len(spawn_points) < 2:
        print(f"Error: Not enough spawn points available ({len(spawn_points)}). Need at least 2 for ego vehicles.")
        client.apply_batch([carla.command.DestroyActor(x) for x in world.get_actors()])
        pygame.quit()
        return
    if not ego_vehicle_bps:
        print("Error: No ego vehicle blueprints available after filtering.")
        client.apply_batch([carla.command.DestroyActor(x) for x in world.get_actors()])
        pygame.quit()
        return

    # Choose distant
    # spawn points for Leader and Follower
    leader_spawn_point = None
    follower_spawn_point = None

    # Try to find two
    # sufficiently distant spawn points
    for i in range(len(spawn_points)):
        for j in range(i + 1, len(spawn_points)):
            # Use a
            # reasonable minimum distance, e.g., 50 meters
            if spawn_points[i].location.distance(spawn_points[j].location) > 50.0:
                leader_spawn_point = spawn_points[i]
                follower_spawn_point = spawn_points[j]
                break
        if leader_spawn_point and follower_spawn_point:
            break

    if not leader_spawn_point or not follower_spawn_point:
        print("🔴 Error: Could not find two sufficiently distant spawn points. Aborting.")
        client.apply_batch([carla.command.DestroyActor(x) for x in world.get_actors()])
        pygame.quit()
        return

    print(f"Attempting to spawn Leader at {leader_spawn_point.location}")
    leader = world.try_spawn_actor(random.choice(ego_vehicle_bps), leader_spawn_point)
    if leader is None:
        print("🔴 Error: Could not spawn Leader vehicle. Aborting.")
        client.apply_batch([carla.command.DestroyActor(x) for x in world.get_actors()])
        pygame.quit()
        return

    print(f"Attempting to spawn Follower at {follower_spawn_point.location}")
    follower = world.try_spawn_actor(random.choice(ego_vehicle_bps), follower_spawn_point)
    if follower is None:
        print("🔴 Error: Could not spawn Follower vehicle. Aborting.")
        leader.destroy()  # Destroy leader if follower fails to spawn
        client.apply_batch([carla.command.DestroyActor(x) for x in world.get_actors()])
        pygame.quit()
        return

    print(f"✅ Leader (ID: {leader.id}) and Follower (ID: {follower.id}) spawned.")

    leader_agent = BehaviorAgent(leader, behavior='aggressive')
    follower_agent = BehaviorAgent(follower, behavior='aggressive')
    # Let's keep 70%
    # chance to ignore traffic lights to facilitate violation tests
    follower_agent.ignore_traffic_lights(random.random() < 0.7)
    leader_agent.set_destination(random.choice(spawn_points).location)

    camera_transform = carla.Transform(carla.Location(x=-5.5, z=2.5))
    camera = world.spawn_actor(camera_bp, camera_transform, attach_to=follower)
    if camera is None:
        print("🔴 Error: Could not spawn camera. Proceeding without camera.")
        image_surface = None  # Ensure image_surface is None if camera isn't present

    image_surface = None
    if camera:
        def process_image(image):
            nonlocal image_surface
            array = np.frombuffer(image.raw_data, dtype=np.uint8)
            array = np.reshape(array, (image.height, image.width, 4))
            array = array[:, :, :3][:, :, ::-1]  # Remove alpha channel and convert BGR to RGB
            image_surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))

        camera.listen(lambda image: process_image(image))

    collision_bp = blueprint_library.find('sensor.other.collision')
    collision_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=follower)
    if collision_sensor is None:
        print("🔴 Error: Could not spawn collision sensor. Proceeding without collision detection.")

    simulation_events = []

    def on_collision(event):
        global _last_collision_time, COLLISION_DEBOUNCE_TIME, running

        actor_id = event.actor.id  # The actor the sensor is attached to (the follower)
        other_actor = event.other_actor  # The actor involved in the collision
        other_actor_id = other_actor.id if other_actor else 'Unknown'
        other_actor_type = other_actor.type_id if other_actor else 'Unknown'

        # Ignore
        # collisions with static objects or specific ones like signs and traffic lights
        ignored_actor_types = ["traffic.speed_limit",
                               "static.prop", "traffic.stop_sign",
                               "traffic.traffic_light", "other.trigger",
                               "sensor.other.collision"]
        if any(ignored_type in other_actor_type for ignored_type in ignored_actor_types):
            return

        # Create a
        # unique key for the pair of actors involved
        sorted_ids = tuple(sorted([actor_id, other_actor_id]))
        collision_key = frozenset(sorted_ids)

        current_time = time.time()

        # If the same
        # pair has recently collided, ignore it
        if (current_time - _last_collision_time.get(collision_key, 0)) < COLLISION_DEBOUNCE_TIME:
            return

        # Register the
        # timestamp of the last collision for this pair
        _last_collision_time[collision_key] = current_time

        current_weather = world.get_weather()
        weather_details = {
            "cloudiness": current_weather.cloudiness,
            "precipitation": current_weather.precipitation,
            "precipitation_deposits": current_weather.precipitation_deposits,
            "wind_intensity": current_weather.wind_intensity,
            "fog_density": current_weather.fog_density,
            "sun_altitude_angle": current_weather.sun_altitude_angle
        }

        # Determine if collision is on a curve or straight road
        collision_road_type = is_collision_on_curve(event.transform.location, carla_map)

        print(f"💥 COLLISION DETECTED! {event.actor.type_id} (ID: {actor_id}) hit "
              f"{other_actor_type} (ID: {other_actor_id}) in {town} with weather: "
              f"{weather_details['cloudiness']}% clouds, {weather_details['precipitation']}% rain. "
              f"Collision occurred on a: {collision_road_type}.")

        # Add the
        # collision event
        simulation_events.append({
            "event_type": "collision",
            "timestamp": f"{current_time:.2f}",  # Format to 2 decimal places
            "actor_id": actor_id,
            "actor_type": event.actor.type_id,
            "other_actor_id": other_actor_id,
            "other_actor_type": other_actor_type,
            "impact_location": {
                "x": event.transform.location.x,
                "y": event.transform.location.y,
                "z": event.transform.location.z
            },
            "town": town,
            "town_characteristics": town_characteristics,  # Include town characteristics
            "road_type_at_collision": collision_road_type,  # Include road type at collision
            "weather": weather_details
        })

        # Stop the
        # simulation immediately after the first detected collision
        print(f"🛑 Immediate simulation stop due to collision.")
        running = False  # Set the flag to terminate the main loop

    if collision_sensor:
        collision_sensor.listen(on_collision)

    # Traffic vehicles
    traffic_vehicles = []
    num_traffic_vehicles_to_spawn = min(130, len(spawn_points))

    print(f"Attempting to spawn {num_traffic_vehicles_to_spawn} traffic vehicles...")
    spawned_vehicle_count = 0
    available_vehicle_spawn_points = list(spawn_points)
    random.shuffle(available_vehicle_spawn_points)

    for i in range(num_traffic_vehicles_to_spawn):
        if not available_vehicle_spawn_points:
            print("  No more spawn points available for traffic vehicles.")
            break
        sp = available_vehicle_spawn_points.pop(0)
        bp = random.choice(traffic_vehicle_bps)
        try:
            vehicle = world.try_spawn_actor(bp, sp)
            if vehicle:
                vehicle.set_autopilot(True, 8000)
                #
                # Randomize traffic behavior further
                if random.random() < 0.4: traffic_manager.ignore_lights_percentage(vehicle, 100)
                # FIX:
                # Corrected random.random() usage
                if random.random() < 0.3: traffic_manager.ignore_vehicles_percentage(vehicle, 50)

                #
                # Speed variation
                speed_diff = random.uniform(-30.0, 20.0)  # Wider range for variety
                traffic_manager.vehicle_percentage_speed_difference(vehicle, speed_diff)
                traffic_manager.distance_to_leading_vehicle(vehicle, random.uniform(0.5, 2.5))  # More varied distance

                traffic_vehicles.append(vehicle)
                spawned_vehicle_count += 1
            else:
                pass
        except Exception as e:
            pass
    print(f"✅ Spawned {spawned_vehicle_count} traffic vehicles out of {num_traffic_vehicles_to_spawn} attempted.")

    # Pedestrians
    pedestrians = []
    pedestrian_controllers = []
    num_pedestrians_to_spawn = min(30,
                                   len(carla_map.get_spawn_points()))  # Use carla_map
    print(f"Attempting to spawn {num_pedestrians_to_spawn} pedestrians...")
    spawned_ped_count = 0

    for i in range(num_pedestrians_to_spawn):
        spawn_location = carla.Location()
        retries = 0
        MAX_RETRIES = 10
        while retries < MAX_RETRIES:
            try:
                #
                # Search for a sidewalk or pedestrian area spawn location
                spawn_location = world.get_random_location_from_navigation()
                if spawn_location:
                    break
            except Exception:
                pass
            retries += 1

        if not spawn_location:
            continue

        ped_transform = carla.Transform(spawn_location + carla.Location(z=0.1), carla.Rotation())
        ped_bp = random.choice(walker_bp)
        ped_bp.set_attribute('is_invincible', 'false')

        try:
            pedestrian = world.try_spawn_actor(ped_bp, ped_transform)
            if pedestrian:
                controller = world.try_spawn_actor(walker_controller_bp,
                                                   carla.Transform(), pedestrian)
                if controller:
                    pedestrians.append(pedestrian)
                    pedestrian_controllers.append(controller)
                    controller.start()
                    controller.go_to_location(world.get_random_location_from_navigation())
                    controller.set_max_speed(1 + random.random() * 1.5)  # Variable
                    # pedestrian speed
                    spawned_ped_count += 1
                else:
                    pedestrian.destroy()
            else:
                pass
        except Exception as e:
            pass
    print(f"✅ Spawned {spawned_ped_count} pedestrians out of {num_pedestrians_to_spawn} attempted.")

    def get_left_overtake_location(actor):
        wp = carla_map.get_waypoint(actor.get_location(), project_to_road=True,
                                    lane_type=carla.LaneType.Driving)
        if wp:
            left_wp = wp.get_left_lane()
            if left_wp and left_wp.lane_type == carla.LaneType.Driving and left_wp.lane_change == \
                    carla.LaneChange.Left:
                forward_left_wp = left_wp.next(15.0)[0] if left_wp.next(15.0) else \
                    left_wp
                return forward_left_wp.transform.location
        return actor.get_location()

    def set_random_weather(world):
        weather_options = [
            carla.WeatherParameters.ClearNoon,
            carla.WeatherParameters.CloudyNoon,
            carla.WeatherParameters(cloudiness=80.0, precipitation=70.0,
                                    precipitation_deposits=50.0, wind_intensity=30.0, fog_density=10.0),
            carla.WeatherParameters(cloudiness=90.0, fog_density=50.0,
                                    fog_distance=10.0, sun_altitude_angle=-20.0),  # Evening/Night with fog
            carla.WeatherParameters(cloudiness=70.0, precipitation=20.0,
                                    precipitation_deposits=30.0),
            carla.WeatherParameters(cloudiness=100.0, precipitation=80.0,
                                    precipitation_deposits=100.0, wind_intensity=50.0),  # Heavy rain/storm
        ]
        chosen_weather = random.choice(weather_options)
        world.set_weather(chosen_weather)
        print(f"☁️ Set weather: Cloudiness={chosen_weather.cloudiness}, "
              f"Precipitation={chosen_weather.precipitation}, "
              f"Precipitation_Deposits={chosen_weather.precipitation_deposits}, "
              f"Fog={chosen_weather.fog_density}")

    SIMULATION_TIMEOUT = 60  # Maximum simulation duration in seconds
    start_time = time.time()

    try:
        while running:  # The loop will continue as long as 'running' is True
            current_time = time.time()
            if (current_time - start_time) >= SIMULATION_TIMEOUT:
                print(f"⏰ Timeout of {SIMULATION_TIMEOUT} seconds reached. Terminating scenario.")
                running = False  # Terminate the loop if timeout is reached

            # Periodic
            # weather change
            if current_time - LAST_WEATHER_CHANGE_TIME > WEATHER_CHANGE_INTERVAL:
                set_random_weather(world)
                LAST_WEATHER_CHANGE_TIME = current_time

            clock.tick(30)  # Limit framerate to 30 FPS
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            world.tick()  # Advance simulation by one tick

            # Leader
            # vehicle management
            if leader and leader.is_alive:
                if leader_agent.done():
                    leader_agent.set_destination(random.choice(spawn_points).location)
                leader.apply_control(leader_agent.run_step())
            else:
                if leader is not None:
                    print("Leader no longer active, terminating simulation.")
                running = False  # Terminate if leader is no longer active

            # Follower
            # (ego) vehicle management
            if follower and follower.is_alive and leader and leader.is_alive:
                #
                # Follower continues to follow leader or overtakes
                dist_to_leader = follower.get_location().distance(leader.get_location())
                follower_speed = math.sqrt(follower.get_velocity().x ** 2 +
                                           follower.get_velocity().y ** 2 + follower.get_velocity().z ** 2) * 3.6
                leader_speed = math.sqrt(leader.get_velocity().x ** 2 +
                                         leader.get_velocity().y ** 2 + leader.get_velocity().z ** 2) * 3.6

                #
                # Logic for left overtaking
                if dist_to_leader < 15.0 and (leader_speed < (follower_speed - 15.0)) and \
                        random.random() < 0.7:
                    overtake_location = get_left_overtake_location(leader)
                    if overtake_location != leader.get_location():
                        follower_agent.set_destination(overtake_location)
                    else:
                        follower_agent.set_destination(leader.get_location())
                else:
                    follower_agent.set_destination(leader.get_location())
                follower.apply_control(follower_agent.run_step())
            elif follower is not None:
                print("Follower no longer active, terminating simulation.")
                running = False  # Terminate if follower is no longer active

            # Pygame
            # display update
            if camera and image_surface:
                display.blit(image_surface, (0, 0))
                pygame.display.flip()
            elif not camera:
                display.fill((0, 0, 0))
                font = pygame.font.Font(pygame.font.get_default_font(), 36)
                text_surface = font.render('No camera active', True, (255, 255, 255))
                text_rect = text_surface.get_rect(center=(display.get_width() / 2,
                                                          display.get_height() / 2))
                display.blit(text_surface, text_rect)
                pygame.display.flip()

    finally:
        print("🧹 Final cleanup...")

        output_dir = "simulation_output"
        os.makedirs(output_dir, exist_ok=True)

        # If no events
        # occurred and the simulation didn't terminate due to timeout
        if not simulation_events:
            print("ℹ️ No incidents or violations recorded. Adding 'no_incidents' entry.")

            final_weather = world.get_weather()
            weather_details = {
                "cloudiness": final_weather.cloudiness,
                "precipitation": final_weather.precipitation,
                "precipitation_deposits": final_weather.precipitation_deposits,
                "wind_intensity": final_weather.wind_intensity,
                "fog_density": final_weather.fog_density,
                "sun_altitude_angle": final_weather.sun_altitude_angle
            }

            simulation_events.append({
                "event_type": "no_incidents",
                "timestamp": f"{time.time():.2f}",  # Format to 2 decimal places
                "message": "No incidents or traffic violations recorded during simulation.",
                "town": town,
                "town_characteristics": town_characteristics,  # Include town characteristics even if no incidents
                "weather": weather_details
            })

        output_filename = os.path.join(output_dir,
                                       f"simulation_events_{int(time.time())}.json")
        with open(output_filename, 'w') as f:
            json.dump(simulation_events, f, indent=4)
        print(f"📝 Simulation data saved to: {output_filename}")

        # Stop sensors
        # before destroying actors
        if collision_sensor and collision_sensor.is_listening:
            collision_sensor.stop()
        if camera and camera.is_listening:
            camera.stop()

        # Destroy all
        # actors
        actors_to_destroy = [leader, follower, camera, collision_sensor] + \
                            traffic_vehicles + pedestrians + pedestrian_controllers
        for actor in actors_to_destroy:
            if actor and actor.is_alive:
                try:
                    actor.destroy()
                except Exception as e:
                    print(f"Error destroying actor {actor.type_id} (ID: {actor.id}): {e}")

        # Reset
        # weather to ClearNoon
        try:
            world.set_weather(carla.WeatherParameters.ClearNoon)
        except Exception as e:
            print(f"Error resetting weather: {e}")

        pygame.quit()


if __name__ == '__main__':
    main()